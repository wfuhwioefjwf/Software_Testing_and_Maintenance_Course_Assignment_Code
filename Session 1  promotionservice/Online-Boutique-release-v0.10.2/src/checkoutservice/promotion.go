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
	"time"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/genproto"
)

type promotionQuoteRequest struct {
	UserID   string         `json:"user_id"`
	Subtotal promotionMoney `json:"subtotal"`
	Shipping promotionMoney `json:"shipping"`
}

type promotionQuote struct {
	Valid      bool           `json:"valid"`
	Code       string         `json:"code"`
	Message    string         `json:"message"`
	Discount   promotionMoney `json:"discount"`
	FinalTotal promotionMoney `json:"final_total"`
}

type promotionMoney struct {
	CurrencyCode string `json:"currency_code"`
	Units        int64  `json:"units"`
	Nanos        int32  `json:"nanos"`
}

func (cs *checkoutService) quotePromotion(ctx context.Context, userID string, subtotal, shipping *pb.Money) (*promotionQuote, error) {
	req := promotionQuoteRequest{
		UserID:   userID,
		Subtotal: promotionMoneyFromProto(subtotal),
		Shipping: promotionMoneyFromProto(shipping),
	}
	var out promotionQuote
	if err := postPromotionJSON(ctx, cs.promotionSvcAddr+"/api/v1/promotions/quote", req, &out); err != nil {
		return nil, err
	}
	if out.FinalTotal.CurrencyCode == "" {
		return nil, fmt.Errorf("promotionservice response missing final_total")
	}
	return &out, nil
}

func postPromotionJSON(ctx context.Context, url string, payload any, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
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
