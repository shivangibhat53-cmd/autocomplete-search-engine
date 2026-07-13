"""
Background health monitor — pings all shards every 5 seconds.

Integrates with circuit breakers:
  - Ping succeeds → record_success() on circuit breaker
  - Ping fails    → record_failure() on circuit breaker
  - Circuit opens → shard removed from hash ring
  - Circuit closes → shard re-added to hash ring
"""
import asyncio
import urllib.request
from src.router_service.circuit_breaker import CircuitBreakerRegistry, CircuitState
from src.sharding.consistent_hash import ConsistentHashRing


class HealthMonitor:

    def __init__(self,
                 clients         : dict,
                 ring            : ConsistentHashRing,
                 breakers        : CircuitBreakerRegistry,
                 interval_seconds: float = 5.0):
        """
        shard_http_ports: dict of shard_name → HTTP port
          e.g. {"shard-1": 8001, "shard-2": 8002, "shard-3": 8003}
        We use HTTP for health checks because it's simpler and more
        reliable than gRPC for liveness detection. gRPC is used for
        actual search requests.
        """
        self.clients  = clients
        self.ring     = ring
        self.breakers = breakers
        self.interval = interval_seconds
        self._task    = None

    async def start(self) -> None:
        """Ping immediately on startup then start the loop."""
        print("Health monitor: initial ping...")
        await self._ping_all_shards()
        self._task = asyncio.create_task(self._monitor_loop())
        print(" Health monitor started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await self._ping_all_shards()

    async def _ping_all_shards(self) -> None: 
        tasks = [
            self._ping_shard(name, client)
            for name, client in self.clients.items()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
                                                            
    
    
 
    async def _ping_shard(self, shard_name: str, client) -> None: 
        """
        Ping one shard and update circuit breaker + ring membership.

        Key logic:
          - Track circuit STATE (not just availability) to detect transitions
          - CLOSED + not in ring → add to ring (recovery)
          - OPEN   + in ring    → remove from ring (failure)
          - HALF_OPEN is a testing state — don't change ring membership yet
        """
        breaker        = self.breakers.get(shard_name)
        in_ring_before = shard_name in self.ring.get_all_shards()

        # Check availability BEFORE pinging
        available = breaker.is_available()
        print(f"  📡 pinging {shard_name}: "
            f"state={breaker.state.value}, "
            f"available={available}, "
            f"in_ring={in_ring_before}")

        if not available:
            print(f"  ⏭️  {shard_name}: skipping ping "
                f"(circuit OPEN, in cooldown)")
            return

        try:
            await client.health()
            breaker.record_success()

            # Only re-add when FULLY recovered (CLOSED), not HALF_OPEN
            if (breaker.state == CircuitState.CLOSED
                    and not in_ring_before):
                self.ring.add_shard(shard_name)
                print(f"    {shard_name} recovered "
                      f"— re-added to ring")

        except Exception as e:
            breaker.record_failure()

            # Only remove when circuit fully opens, not on first failure
            if (breaker.state == CircuitState.OPEN
                    and in_ring_before):
                self.ring.remove_shard(shard_name)
                print(f"   {shard_name} down "
                      f"— removed from ring: {e}")
                                                     
    
    async def _ping_shard(self, shard_name: str, client) -> None:
        breaker        = self.breakers.get(shard_name)
        in_ring_before = shard_name in self.ring.get_all_shards()

        # Check availability BEFORE pinging
        available = breaker.is_available()
        print(f"  📡 pinging {shard_name}: "
            f"state={breaker.state.value}, "
            f"available={available}, "
            f"in_ring={in_ring_before}")

        if not available:
            print(f"  ⏭️  {shard_name}: skipping ping "
                f"(circuit OPEN, in cooldown)")
            return

        try:
            await client.health()
            breaker.record_success()

            if (breaker.state == CircuitState.CLOSED
                and not in_ring_before):
                self.ring.add_shard(shard_name)
                print(f"  ♻️  {shard_name} recovered "
                  f"— re-added to ring")

        except Exception as e:
            breaker.record_failure()

            if (breaker.state == CircuitState.OPEN
                and in_ring_before):
                self.ring.remove_shard(shard_name)
                print(f"  💀 {shard_name} down "
                  f"— removed from ring: {e}")