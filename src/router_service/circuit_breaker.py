"""
Circuit Breaker pattern for shard fault tolerance.

States:
  CLOSED   → normal operation, requests flow through
  OPEN     → shard is down, requests fail fast (no waiting)
  HALF_OPEN → testing if shard recovered, let one request through

Why circuit breaker instead of just retrying?
  Without it, every request to a dead shard waits for a timeout
  (e.g. 5 seconds) before failing. Under load, this creates a
  thundering herd — thousands of requests all waiting 5s each,
  exhausting connection pools and cascading failures across the system.

  With circuit breaker:
  - After N failures, open the circuit immediately
  - Fail fast (< 1ms) instead of waiting for timeout
  - Try again after a cooldown period
  - Close circuit if shard recovers
"""
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED    = "closed"      # healthy, accepting requests
    OPEN      = "open"        # down, failing fast
    HALF_OPEN = "half_open"   # testing recovery


class CircuitBreaker:
    """
    Per-shard circuit breaker.

    Configuration:
      failure_threshold : how many consecutive failures before opening
      recovery_timeout  : seconds to wait before testing recovery
      success_threshold : consecutive successes needed to close again
    """

    def __init__(self,
                 shard_name       : str,
                 failure_threshold: int   = 3,
                 recovery_timeout : float = 10.0, # ← reduced from 30
                 success_threshold: int   = 2):
        self.shard_name        = shard_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout  = recovery_timeout
        self.success_threshold = success_threshold

        self.state             = CircuitState.CLOSED
        self.failure_count     = 0
        self.success_count     = 0
        self.last_failure_time = None

    def is_available(self) -> bool:
        """
        Can we send a request to this shard right now?

        CLOSED    → yes
        OPEN      → only if recovery_timeout has elapsed (try half-open)
        HALF_OPEN → yes (we're testing recovery)
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time is None:
                # No failure time recorded — should not happen
                # but recover gracefully
                print(f"  ⚠️  {self.shard_name}: OPEN but no "
                      f"last_failure_time — forcing HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                return True
            elapsed = time.time() - (self.last_failure_time or 0)
            print(f"  🔍 {self.shard_name}: OPEN, "
                  f"elapsed={elapsed:.1f}s, "
                  f"timeout={self.recovery_timeout}s, "
                  f"ready={elapsed >= self.recovery_timeout}")

            if elapsed >= self.recovery_timeout:
                self.state         = CircuitState.HALF_OPEN
                self.success_count = 0
                print(f" {self.shard_name}: OPEN → HALF_OPEN "
                      f"(testing recovery)")
                return True
            return False   # still in cooldown, fail fast

        # HALF_OPEN — let the request through
        return True

    def record_success(self) -> None:
        """
        Called when a shard request succeeds.
        In HALF_OPEN: count successes, close circuit after threshold.
        In CLOSED: reset failure count.
        """
        self.failure_count = 0
        print(f"  ✓ {self.shard_name}: success recorded, "
              f"state={self.state.value}, "
              f"success_count={self.success_count}")

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitState.CLOSED
                print(f"{self.shard_name}: HALF_OPEN → CLOSED "
                      f"(recovered)")

    def record_failure(self) -> None:
        """
        Called when a shard request fails.
        Increments failure count and opens circuit if threshold reached.
        """
        self.failure_count    += 1
        self.success_count     = 0
        print(f"  ✗ {self.shard_name}: failure recorded, "
              f"state={self.state.value}, "
              f"failures={self.failure_count}/{self.failure_threshold}")

        if self.state == CircuitState.HALF_OPEN:
            # Failed during recovery test — back to OPEN
            # Reset the clock so we wait the full timeout again
            self.last_failure_time = time.time()
            self.state = CircuitState.OPEN
            print(f"{self.shard_name}: HALF_OPEN → OPEN "
                  f"(recovery failed)")
        elif self.state == CircuitState.CLOSED: 
            if self.failure_count >= self.failure_threshold:
                # Circuit just opened — start the recovery clock NOW
                self.last_failure_time = time.time()
                self.state = CircuitState.OPEN
                print(f"{self.shard_name}: CLOSED → OPEN "
                        f"({self.failure_count} consecutive failures)")
            # Don't update last_failure_time for failures below threshold
        
        elif self.state == CircuitState.OPEN:
            # Already open — do NOT reset last_failure_time
            # The clock started when it first opened and must not reset
            # Otherwise the shard can never recover — every failed ping
            # would push the recovery window further into the future
            #pass   # ← this is the key fix
            print(f"  ℹ️  {self.shard_name}: already OPEN, "
                  f"last_failure={time.time() - self.last_failure_time:.1f}s ago")

    @property
    def status(self) -> str:
        return self.state.value


class CircuitBreakerRegistry:
    """
    Manages circuit breakers for all shards.
    One CircuitBreaker per shard, created on demand.
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, shard_name: str) -> CircuitBreaker:
        if shard_name not in self._breakers:
            self._breakers[shard_name] = CircuitBreaker(shard_name)
        return self._breakers[shard_name]

    def all_statuses(self) -> dict:
        return {
            name: breaker.status
            for name, breaker in self._breakers.items()
        }

    def healthy_shards(self) -> list[str]:
        return [
            name for name, breaker in self._breakers.items()
            if breaker.is_available()
        ]