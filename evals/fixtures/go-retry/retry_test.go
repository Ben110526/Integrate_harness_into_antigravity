package retry

import (
	"errors"
	"testing"
)

func TestRetryHonorsMaximumAttempts(t *testing.T) {
	want := errors.New("unavailable")
	calls := 0
	err := Retry(3, func() error {
		calls++
		return want
	})
	if !errors.Is(err, want) {
		t.Fatalf("Retry() error = %v, want %v", err, want)
	}
	if calls != 3 {
		t.Fatalf("Retry() calls = %d, want 3", calls)
	}
}
