"""Public waiting-list interface for a small event registration service."""


class WaitingList:
    def __init__(self, capacity):
        self.capacity = capacity
        self.names = []

    def join(self, name):
        """Join and return a one-based position."""
        self.names.append(name)
        return len(self.names)

    def snapshot(self):
        """Return the current waiting names."""
        return self.names

    def cancel(self, name):
        """Cancel a name and return whether it was present."""
        raise NotImplementedError

    def position(self, name):
        """Return a one-based position, or None when absent."""
        raise NotImplementedError

    def next(self):
        """Remove and return the next name, or None when empty."""
        raise NotImplementedError

    def join_many(self, names):
        """Join several names and return their one-based positions."""
        raise NotImplementedError
