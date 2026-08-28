pub fn clamp_window(value: usize, lower: usize, upper: usize) -> usize {
    if value < lower {
        lower
    } else if value >= upper {
        upper.saturating_sub(1)
    } else {
        value
    }
}

#[cfg(test)]
mod tests {
    use super::clamp_window;

    #[test]
    fn keeps_the_inclusive_upper_bound() {
        assert_eq!(clamp_window(10, 2, 10), 10);
    }

    #[test]
    fn clamps_values_outside_the_window() {
        assert_eq!(clamp_window(1, 2, 10), 2);
        assert_eq!(clamp_window(11, 2, 10), 10);
    }
}
