package retry

func Retry(maxAttempts int, operation func() error) error {
	var err error
	for attempt := 0; attempt <= maxAttempts; attempt++ {
		if err = operation(); err == nil {
			return nil
		}
	}
	return err
}
