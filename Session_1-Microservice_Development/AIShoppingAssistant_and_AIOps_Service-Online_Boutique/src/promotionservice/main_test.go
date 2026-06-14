package main

import "testing"

func TestCalculateQuoteSave10(t *testing.T) {
	resp := calculateQuote(quoteRequest{
		Code:     "SAVE10",
		Subtotal: money{CurrencyCode: "USD", Units: 50},
		Shipping: money{CurrencyCode: "USD", Units: 5},
	})
	if !resp.Valid {
		t.Fatalf("SAVE10 should be valid: %s", resp.Message)
	}
	if got, want := cents(resp.Discount), int64(500); got != want {
		t.Fatalf("discount cents = %d, want %d", got, want)
	}
	if got, want := cents(resp.FinalTotal), int64(5000); got != want {
		t.Fatalf("final cents = %d, want %d", got, want)
	}
}

func TestCalculateQuoteWelcome5Minimum(t *testing.T) {
	resp := calculateQuote(quoteRequest{
		Code:     "WELCOME5",
		Subtotal: money{CurrencyCode: "USD", Units: 24, Nanos: 990000000},
		Shipping: money{CurrencyCode: "USD", Units: 5},
	})
	if resp.Valid {
		t.Fatal("WELCOME5 should be invalid below the minimum subtotal")
	}
	if got := cents(resp.Discount); got != 0 {
		t.Fatalf("discount cents = %d, want 0", got)
	}
}

func TestCalculateQuoteFreeShip(t *testing.T) {
	resp := calculateQuote(quoteRequest{
		Code:     "FREESHIP",
		Subtotal: money{CurrencyCode: "USD", Units: 30},
		Shipping: money{CurrencyCode: "USD", Units: 8, Nanos: 990000000},
	})
	if !resp.Valid {
		t.Fatalf("FREESHIP should be valid: %s", resp.Message)
	}
	if got, want := cents(resp.Discount), int64(899); got != want {
		t.Fatalf("discount cents = %d, want %d", got, want)
	}
}
