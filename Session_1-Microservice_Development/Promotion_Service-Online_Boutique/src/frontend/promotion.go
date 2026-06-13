// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/pkg/errors"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
)

type promotionQuoteRequest struct {
	UserID   string         `json:"user_id"`
	Code     string         `json:"code"`
	Subtotal promotionMoney `json:"subtotal"`
	Shipping promotionMoney `json:"shipping"`
}

type promotionSessionRequest struct {
	UserID string `json:"user_id"`
	Code   string `json:"code"`
}

type promotionQuote struct {
	Valid      bool           `json:"valid"`
	Code       string         `json:"code"`
	Message    string         `json:"message"`
	Discount   promotionMoney `json:"discount"`
	FinalTotal promotionMoney `json:"final_total"`
}

type promotionView struct {
	Valid      bool
	Code       string
	Message    string
	Discount   *pb.Money
	FinalTotal *pb.Money
}

type promotionMoney struct {
	CurrencyCode string `json:"currency_code"`
	Units        int64  `json:"units"`
	Nanos        int32  `json:"nanos"`
}

func (fe *frontendServer) quotePromotion(ctx context.Context, userID, code string, subtotal, shipping *pb.Money) (*promotionQuote, error) {
	if fe.promotionSvcAddr == "" {
		return nil, nil
	}
	req := promotionQuoteRequest{
		UserID:   userID,
		Code:     strings.TrimSpace(code),
		Subtotal: promotionMoneyFromProto(subtotal),
		Shipping: promotionMoneyFromProto(shipping),
	}
	var out promotionQuote
	if err := postPromotionJSON(ctx, fe.promotionSvcAddr+"/api/v1/promotions/quote", req, &out); err != nil {
		return nil, errors.Wrap(err, "failed to quote promotion")
	}
	return &out, nil
}

func (fe *frontendServer) savePromotionCode(ctx context.Context, userID, code string) error {
	if fe.promotionSvcAddr == "" {
		return nil
	}
	req := promotionSessionRequest{
		UserID: userID,
		Code:   strings.TrimSpace(code),
	}
	return postPromotionJSON(ctx, fe.promotionSvcAddr+"/api/v1/promotions/session", req, nil)
}

func postPromotionJSON(ctx context.Context, url string, payload any, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, 300*time.Millisecond)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("promotionservice returned HTTP %d", resp.StatusCode)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func promotionMoneyFromProto(m *pb.Money) promotionMoney {
	if m == nil {
		return promotionMoney{}
	}
	return promotionMoney{
		CurrencyCode: m.GetCurrencyCode(),
		Units:        m.GetUnits(),
		Nanos:        m.GetNanos(),
	}
}

func (m promotionMoney) proto() *pb.Money {
	return &pb.Money{
		CurrencyCode: m.CurrencyCode,
		Units:        m.Units,
		Nanos:        m.Nanos,
	}
}

func (q *promotionQuote) view() *promotionView {
	if q == nil {
		return nil
	}
	return &promotionView{
		Valid:      q.Valid,
		Code:       q.Code,
		Message:    q.Message,
		Discount:   q.Discount.proto(),
		FinalTotal: q.FinalTotal.proto(),
	}
}
