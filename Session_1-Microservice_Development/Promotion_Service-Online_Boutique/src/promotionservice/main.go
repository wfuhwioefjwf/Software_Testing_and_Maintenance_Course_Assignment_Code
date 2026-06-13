package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	defaultPort = "8080"
	currencyUSD = "USD"
)

type money struct {
	CurrencyCode string `json:"currency_code"`
	Units        int64  `json:"units"`
	Nanos        int32  `json:"nanos"`
}

type quoteRequest struct {
	UserID   string `json:"user_id"`
	Code     string `json:"code"`
	Subtotal money  `json:"subtotal"`
	Shipping money  `json:"shipping"`
}

type quoteResponse struct {
	Valid      bool   `json:"valid"`
	Code       string `json:"code"`
	Message    string `json:"message"`
	Discount   money  `json:"discount"`
	FinalTotal money  `json:"final_total"`
}

type sessionRequest struct {
	UserID string `json:"user_id"`
	Code   string `json:"code"`
}

type server struct {
	mu       sync.RWMutex
	sessions map[string]string
	metrics  serviceMetrics
}

type serviceMetrics struct {
	requests      uint64
	quoteRequests uint64
	errors        uint64
	durationNanos uint64
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = defaultPort
	}

	s := &server{sessions: map[string]string{}}
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", s.healthz)
	mux.HandleFunc("/metrics", s.metricsHandler)
	mux.HandleFunc("/api/v1/promotions/session", s.sessionHandler)
	mux.HandleFunc("/api/v1/promotions/quote", s.quoteHandler)

	log.Printf("promotionservice listening on :%s", port)
	log.Fatal(http.ListenAndServe(":"+port, s.withMetrics(mux)))
}

func (s *server) withMetrics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		atomic.AddUint64(&s.metrics.requests, 1)
		next.ServeHTTP(w, r)
		atomic.AddUint64(&s.metrics.durationNanos, uint64(time.Since(start)))
	})
}

func (s *server) healthz(w http.ResponseWriter, _ *http.Request) {
	fmt.Fprint(w, "ok")
}

func (s *server) metricsHandler(w http.ResponseWriter, _ *http.Request) {
	requests := atomic.LoadUint64(&s.metrics.requests)
	quotes := atomic.LoadUint64(&s.metrics.quoteRequests)
	errors := atomic.LoadUint64(&s.metrics.errors)
	duration := atomic.LoadUint64(&s.metrics.durationNanos)

	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "# HELP promotionservice_requests_total Total HTTP requests handled by promotionservice.\n")
	fmt.Fprintf(w, "# TYPE promotionservice_requests_total counter\n")
	fmt.Fprintf(w, "promotionservice_requests_total %d\n", requests)
	fmt.Fprintf(w, "# HELP promotionservice_quote_requests_total Total promotion quote requests.\n")
	fmt.Fprintf(w, "# TYPE promotionservice_quote_requests_total counter\n")
	fmt.Fprintf(w, "promotionservice_quote_requests_total %d\n", quotes)
	fmt.Fprintf(w, "# HELP promotionservice_errors_total Total request errors.\n")
	fmt.Fprintf(w, "# TYPE promotionservice_errors_total counter\n")
	fmt.Fprintf(w, "promotionservice_errors_total %d\n", errors)
	fmt.Fprintf(w, "# HELP promotionservice_request_duration_seconds_sum Total request duration in seconds.\n")
	fmt.Fprintf(w, "# TYPE promotionservice_request_duration_seconds summary\n")
	fmt.Fprintf(w, "promotionservice_request_duration_seconds_sum %.9f\n", float64(duration)/float64(time.Second))
	fmt.Fprintf(w, "promotionservice_request_duration_seconds_count %d\n", requests)
}

func (s *server) sessionHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req sessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		atomic.AddUint64(&s.metrics.errors, 1)
		http.Error(w, "invalid session request", http.StatusBadRequest)
		return
	}
	req.UserID = strings.TrimSpace(req.UserID)
	req.Code = normalizeCode(req.Code)
	if req.UserID == "" {
		atomic.AddUint64(&s.metrics.errors, 1)
		http.Error(w, "user_id is required", http.StatusBadRequest)
		return
	}

	s.mu.Lock()
	if req.Code == "" {
		delete(s.sessions, req.UserID)
	} else {
		s.sessions[req.UserID] = req.Code
	}
	s.mu.Unlock()

	writeJSON(w, http.StatusOK, map[string]string{
		"user_id": req.UserID,
		"code":    req.Code,
		"message": "promotion session updated",
	})
}

func (s *server) quoteHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	atomic.AddUint64(&s.metrics.quoteRequests, 1)

	var req quoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		atomic.AddUint64(&s.metrics.errors, 1)
		http.Error(w, "invalid quote request", http.StatusBadRequest)
		return
	}
	req.Code = normalizeCode(req.Code)
	req.UserID = strings.TrimSpace(req.UserID)
	if req.Code == "" && req.UserID != "" {
		req.Code = s.sessionCode(req.UserID)
	}

	resp := calculateQuote(req)
	if resp.Valid && req.UserID != "" {
		s.saveSessionCode(req.UserID, resp.Code)
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *server) sessionCode(userID string) string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.sessions[userID]
}

func (s *server) saveSessionCode(userID, code string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if code == "" {
		delete(s.sessions, userID)
		return
	}
	s.sessions[userID] = code
}

func calculateQuote(req quoteRequest) quoteResponse {
	subtotal := cents(req.Subtotal)
	shipping := cents(req.Shipping)
	total := subtotal + shipping
	discount := int64(0)
	message := "No promotion code applied."
	valid := true

	switch req.Code {
	case "":
	case "SAVE10":
		discount = int64(math.Round(float64(subtotal) * 0.10))
		message = "SAVE10 applied: 10% off merchandise."
	case "WELCOME5":
		if subtotal >= 2500 {
			discount = 500
			message = "WELCOME5 applied: $5 off orders over $25."
		} else {
			valid = false
			message = "WELCOME5 requires a merchandise subtotal of at least $25."
		}
	case "FREESHIP":
		discount = shipping
		message = "FREESHIP applied: shipping cost removed."
	default:
		valid = false
		message = "Promotion code is not valid."
	}

	if !valid {
		discount = 0
	}
	if discount > total {
		discount = total
	}

	currency := req.Subtotal.CurrencyCode
	if currency == "" {
		currency = req.Shipping.CurrencyCode
	}
	if currency == "" {
		currency = currencyUSD
	}

	return quoteResponse{
		Valid:      valid,
		Code:       req.Code,
		Message:    message,
		Discount:   moneyFromCents(currency, discount),
		FinalTotal: moneyFromCents(currency, total-discount),
	}
}

func normalizeCode(code string) string {
	return strings.ToUpper(strings.TrimSpace(code))
}

func cents(m money) int64 {
	return m.Units*100 + int64(math.Round(float64(m.Nanos)/10000000.0))
}

func moneyFromCents(currency string, value int64) money {
	units := value / 100
	nanos := int32((value % 100) * 10000000)
	return money{CurrencyCode: currency, Units: units, Nanos: nanos}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
