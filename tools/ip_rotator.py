# -*- coding: utf-8 -*-
"""
IP Rotator — Rotação de IPv6 residencial com proxy SOCKS5 local.

Usa o prefixo /64 da sua rede para gerar endereços IPv6 aleatórios.
Cada conta pode usar um IPv6 diferente, evitando rate limiting
sem usar VPN/datacenter (que são bloqueados).

Como funciona:
1. Detecta o prefixo /64 da rede automaticamente
2. Gera um sufixo aleatório → novo IPv6 único
3. Adiciona o IPv6 à interface de rede (requer Administrador)
4. Proxy SOCKS5 local roteia tráfego usando esse IPv6 como source
5. CloakBrowser conecta pelo proxy → sai com o IPv6 rotacionado
6. Para rotacionar: remove o antigo, adiciona novo (proxy continua)
7. No final: limpa TODOS os IPv6 adicionados (sem lixo)

Requisitos:
- Terminal rodando como Administrador (para netsh)
- ISP com suporte a IPv6 (prefixo /64)
- O resto do PC NÃO é afetado (proxy é local)
"""
import asyncio
import atexit
import ctypes
import ipaddress
import random
import socket
import struct
import subprocess
from typing import Optional

# ---- Cleanup global (segurança contra crash) ----
_cleanup_registry: list[tuple[str, str]] = []  # (interface, address)


def _emergency_cleanup():
    """Remove todos os IPv6 adicionados — roda mesmo em crash."""
    for iface, addr in _cleanup_registry:
        try:
            subprocess.run(
                ["netsh", "interface", "ipv6", "delete", "address", iface, addr],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    _cleanup_registry.clear()


atexit.register(_emergency_cleanup)


def _is_admin() -> bool:
    """Verifica se o terminal está rodando como Administrador."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class _SuppressAll:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return True


class IPRotator:
    """
    Rotação de IPv6 residencial com proxy SOCKS5 local.

    Gera endereços IPv6 aleatórios dentro do prefixo /64 da rede.
    Um proxy SOCKS5 local roteia o tráfego usando o IPv6 como source.
    O resto do PC NÃO é afetado.
    """

    def __init__(self, port: int = 40000):
        self.port = port
        self.interface_name: Optional[str] = None
        self.prefix: Optional[ipaddress.IPv6Network] = None
        self.current_ipv6: Optional[str] = None
        self._added_addresses: list[str] = []
        self._proxy_task: Optional[asyncio.Task] = None
        self._proxy_ready = asyncio.Event()
        self._source_ipv6: Optional[str] = None
        self._setup_done = False

    @property
    def proxy_url(self) -> str:
        return f"socks5://127.0.0.1:{self.port}"

    # ---- Setup ----

    async def setup(self) -> bool:
        """Detecta interface e prefixo IPv6."""
        if self._setup_done:
            return True

        if not _is_admin():
            print("  ❌ Requer terminal como Administrador para rotação de IPv6!")
            print("     💡 Clique direito no terminal → Executar como administrador")
            return False

        self.interface_name = self._detect_interface()
        if not self.interface_name:
            print("  ❌ Nenhuma interface de rede com IPv6 encontrada!")
            return False

        self.prefix = self._get_ipv6_prefix()
        if not self.prefix:
            print("  ❌ Não encontrou prefixo IPv6 /64 na interface!")
            print("     💡 Verifique se seu ISP suporta IPv6")
            return False

        print(f"  🌐 IPv6 detectado: {self.prefix} ({self.interface_name})")
        self._setup_done = True
        return True

    # ---- Connect / Rotate / Cleanup ----

    async def start(self) -> bool:
        """Inicia o proxy SOCKS5 e faz primeira rotação de IPv6."""
        if not await self.setup():
            return False

        self._kill_port_process(self.port)

        self._proxy_ready.clear()
        self._proxy_task = asyncio.create_task(self._run_socks5_proxy())
        try:
            await asyncio.wait_for(self._proxy_ready.wait(), timeout=8)
        except asyncio.TimeoutError:
            print("  ❌ Proxy SOCKS5 não iniciou!")
            return False

        return await self.rotate()

    async def rotate(self) -> bool:
        """Rotaciona para um novo IPv6. O proxy continua rodando."""
        if not self._setup_done:
            if not await self.setup():
                return False

        old_ipv6 = self.current_ipv6

        new_ipv6 = self._generate_random_ipv6()
        if not self._add_ipv6(new_ipv6):
            return False
        self.current_ipv6 = new_ipv6
        self._source_ipv6 = new_ipv6

        # Wait for DAD (Duplicate Address Detection) ~1.5s
        await asyncio.sleep(1.5)

        if old_ipv6:
            self._remove_ipv6(old_ipv6)

        return True

    async def stop(self):
        """Remove TODOS os IPv6 adicionados e para o proxy."""
        if self._proxy_task:
            self._proxy_task.cancel()
            try:
                await self._proxy_task
            except (asyncio.CancelledError, Exception):
                pass
            self._proxy_task = None
        for addr in self._added_addresses[:]:
            self._remove_ipv6(addr)
        self._added_addresses.clear()
        self.current_ipv6 = None
        self._source_ipv6 = None

    # ---- Interface / Prefix detection (Windows) ----

    def _detect_interface(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetIPAddress -AddressFamily IPv6 | "
                 "Where-Object { $_.PrefixOrigin -eq 'RouterAdvertisement' "
                 "-and $_.AddressState -eq 'Preferred' "
                 "-and $_.PrefixLength -le 64 } | "
                 "Select-Object -First 1 -ExpandProperty InterfaceAlias"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _get_ipv6_prefix(self) -> Optional[ipaddress.IPv6Network]:
        if not self.interface_name:
            return None
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Get-NetIPAddress -AddressFamily IPv6 "
                 f"-InterfaceAlias '{self.interface_name}' | "
                 "Where-Object { $_.PrefixOrigin -eq 'RouterAdvertisement' "
                 "-and $_.AddressState -eq 'Preferred' "
                 "-and $_.PrefixLength -le 64 } | "
                 "Select-Object -First 1 | "
                 "ForEach-Object { \"$($_.IPAddress)/$($_.PrefixLength)\" }"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                addr_with_prefix = result.stdout.strip()
                network = ipaddress.IPv6Network(addr_with_prefix, strict=False)
                if network.prefixlen <= 64:
                    return ipaddress.IPv6Network(
                        f"{network.network_address}/64", strict=False
                    )
                return network
        except Exception:
            pass
        return None

    # ---- IPv6 address management (netsh) ----

    def _generate_random_ipv6(self) -> str:
        if not self.prefix:
            raise RuntimeError("No IPv6 prefix detected")
        prefix_int = int(self.prefix.network_address)
        suffix = random.getrandbits(64)
        suffix = max(suffix, 0x100)
        new_addr = ipaddress.IPv6Address(prefix_int | suffix)
        return str(new_addr)

    def _add_ipv6(self, addr: str) -> bool:
        try:
            result = subprocess.run(
                ["netsh", "interface", "ipv6", "add", "address",
                 self.interface_name, addr],
                capture_output=True, text=True, timeout=10,
            )
            combined = (result.stdout + result.stderr).lower()
            if result.returncode == 0 or "already" in combined:
                self._added_addresses.append(addr)
                _cleanup_registry.append((self.interface_name, addr))
                return True
            print(f"  ❌ Failed to add IPv6: {result.stdout.strip()} {result.stderr.strip()}")
            return False
        except Exception as e:
            print(f"  ❌ Error adding IPv6: {e}")
            return False

    def _remove_ipv6(self, addr: str):
        try:
            subprocess.run(
                ["netsh", "interface", "ipv6", "delete", "address",
                 self.interface_name, addr],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass
        if addr in self._added_addresses:
            self._added_addresses.remove(addr)
        pair = (self.interface_name, addr)
        if pair in _cleanup_registry:
            _cleanup_registry.remove(pair)

    # ---- SOCKS5 Proxy ----

    def _kill_port_process(self, port: int):
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) > 0:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            capture_output=True, timeout=5,
                        )
        except Exception:
            pass

    async def _run_socks5_proxy(self):
        server = None
        for port in [self.port, self.port + 1, self.port + 2]:
            try:
                server = await asyncio.start_server(
                    self._handle_socks5_client,
                    "127.0.0.1", port,
                )
                self.port = port
                break
            except OSError:
                continue

        if not server:
            print(f"  ❌ Não conseguiu abrir proxy SOCKS5 (portas {self.port}-{self.port+2} ocupadas)")
            return

        self._proxy_ready.set()
        print(f"  🔌 Proxy SOCKS5 ativo em 127.0.0.1:{self.port}")
        async with server:
            await server.serve_forever()

    async def _handle_socks5_client(self, client_reader, client_writer):
        source = self._source_ipv6
        try:
            # Auth negotiation
            data = await asyncio.wait_for(client_reader.read(256), timeout=10)
            if not data or data[0] != 5:
                return
            client_writer.write(b"\x05\x00")
            await client_writer.drain()

            # Connection request
            data = await asyncio.wait_for(client_reader.read(512), timeout=10)
            if not data or len(data) < 4:
                return
            ver, cmd, rsv, atyp = data[0], data[1], data[2], data[3]
            if cmd != 1:
                client_writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                await client_writer.drain()
                return

            # Parse target
            if atyp == 1:  # IPv4
                target_host = socket.inet_ntoa(data[4:8])
                target_port = struct.unpack("!H", data[8:10])[0]
            elif atyp == 3:  # Domain
                dlen = data[4]
                target_host = data[5:5 + dlen].decode()
                target_port = struct.unpack("!H", data[5 + dlen:7 + dlen])[0]
            elif atyp == 4:  # IPv6
                target_host = socket.inet_ntop(socket.AF_INET6, data[4:20])
                target_port = struct.unpack("!H", data[20:22])[0]
            else:
                return

            # Connect with source binding
            remote_reader, remote_writer = await self._connect_to_target(
                target_host, target_port, source
            )

            # Success
            client_writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
            await client_writer.drain()

            # Bidirectional relay
            await asyncio.gather(
                self._relay(client_reader, remote_writer),
                self._relay(remote_reader, client_writer),
                return_exceptions=True,
            )
        except Exception:
            pass
        finally:
            with _SuppressAll():
                client_writer.close()

    async def _connect_to_target(self, host, port, source_ipv6):
        loop = asyncio.get_event_loop()

        # Try IPv6 with source binding
        if source_ipv6:
            try:
                infos = await loop.getaddrinfo(
                    host, port, family=socket.AF_INET6, type=socket.SOCK_STREAM
                )
                if infos:
                    af, socktype, proto, _, sockaddr = infos[0]
                    sock = socket.socket(af, socktype, proto)
                    sock.setblocking(False)
                    sock.bind((source_ipv6, 0, 0, 0))
                    await loop.sock_connect(sock, sockaddr)
                    return await asyncio.open_connection(sock=sock)
            except Exception:
                pass

        # Fallback: normal connection
        return await asyncio.open_connection(host, port)

    async def _relay(self, reader, writer):
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            with _SuppressAll():
                writer.close()
