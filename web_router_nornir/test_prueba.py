import asyncio
import time
from pysnmp.hlapi.v3arch.asyncio import *


# --- CONFIGURACIÓN ---
IP_ROUTER = "10.235.0.0"
COMUNIDAD = "Perl3t5"
INDEX_WAN = 763
INTERVALO_SEG = 5


# OIDs Familia IPv4 (.1)
OID_V4_IN  = f"1.3.6.1.2.1.4.31.3.1.6.1.{INDEX_WAN}"
OID_V4_OUT = f"1.3.6.1.2.1.4.31.3.1.33.1.{INDEX_WAN}"


# OIDs Familia IPv6 (.2)
OID_V6_IN  = f"1.3.6.1.2.1.4.31.3.1.6.2.{INDEX_WAN}"
OID_V6_OUT = f"1.3.6.1.2.1.4.31.3.1.33.2.{INDEX_WAN}"


async def consultar_valor(oid, engine):
    try:
        errorIndication, errorStatus, _, varBinds = await get_cmd(
            engine,
            CommunityData(COMUNIDAD),
            await UdpTransportTarget.create((IP_ROUTER, 161), timeout=1, retries=0),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        if not errorIndication and not errorStatus:
            return int(varBinds[0][1])
    except:
        return None
    return None


async def snapshot_total(engine):
    """Captura los 4 contadores al mismo tiempo"""
    return await asyncio.gather(
        consultar_valor(OID_V4_IN, engine),
        consultar_valor(OID_V4_OUT, engine),
        consultar_valor(OID_V6_IN, engine),
        consultar_valor(OID_V6_OUT, engine)
    )


async def main():
    engine = SnmpEngine()
    print(f"\n[Analizando Eth-Trunk31 en {IP_ROUTER} por {INTERVALO_SEG}s...]\n")
    
    # Snapshot 1
    t1 = time.time()
    v1 = await snapshot_total(engine)
    
    if None in v1:
        print("Error: No se pudo obtener alguno de los contadores. Verifica soporte IPv6/SNMP.")
        return


    await asyncio.sleep(INTERVALO_SEG)
    
    # Snapshot 2
    t2 = time.time()
    v2 = await snapshot_total(engine)
    
    delta_t = t2 - t1
    
    # Cálculos (Bytes a Gbps)
    def calc_gbps(start, end):
        return ((end - start) * 8) / delta_t / 1_000_000_000


    g4_in  = calc_gbps(v1[0], v2[0])
    g4_out = calc_gbps(v1[1], v2[1])
    g6_in  = calc_gbps(v1[2], v2[2])
    g6_out = calc_gbps(v1[3], v2[3])


    # Mostrar Resultados
    print(f"RESULTADOS DEL MUESTREO ({delta_t:.2f} segundos):")
    print("-" * 55)
    print(f" PROTOCOLO |   ENTRADA (In)    |    SALIDA (Out)    ")
    print("-" * 55)
    print(f" IPv4      |  {g4_in:10.6f} Gbps |  {g4_out:10.6f} Gbps")
    print(f" IPv6      |  {g6_in:10.6f} Gbps |  {g6_out:10.6f} Gbps")
    print("-" * 55)
    print(f" TOTAL     |  {(g4_in + g6_in):10.6f} Gbps |  {(g4_out + g6_out):10.6f} Gbps")
    print("-" * 55)


if __name__ == "__main__":
    asyncio.run(main())




