"""Cliente da DelfosCentralFT.

``Central`` envolve ``SerialTransport`` + ``delfos.protocol`` e expõe um método
por comando do protocolo. Cada método valida parâmetros via ``CommandSpec``,
envia o frame, decodifica a resposta e devolve um dataclass tipado quando há
payload relevante. Retry interno (``n_tries=5`` default) cobre falhas de eco.

Não imprime, não loga em stdout, não toca disco. Eventos vão pelo EventBus em
camadas superiores.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from delfos._adc import (
    ADC_CORRENTE,
    ADC_SP,
    ADC_TENSAO,
    ADC_VARVP,
    ADC_VP,
    convert_adc,
)
from delfos.protocol import (
    BROADCAST_ADDR,
    SOF,
    Command,
    CurrentControlMode,
    CurrentCycleType,
    CyclePeriod,
    ElectrodeE3Mode,
    ElectrodeMode,
    GeoVariable,
    ResponseFrame,
    SismicState,
    addr_join,
    build_command_frame,
)

# =============================================================================
# Dataclasses de leitura (decodificadas)
# =============================================================================


@dataclass(frozen=True)
class CurrentReading:
    """Resposta a INF_CORRENTE_TRANSM ou frame autônomo emitido pelo ciclo IP."""

    tensao: float
    corrente: float
    tensao_raw: int
    corrente_raw: int
    raw: bytes


@dataclass(frozen=True)
class CurrentCycleSample:
    """Uma amostra do ciclo de corrente — entregue durante ``run_current_cycle``."""

    tensao: float
    corrente: float
    count: int  # contador decrescente do firmware (0 = fim do ciclo)
    raw: bytes


@dataclass(frozen=True)
class CurrentCycleResult:
    """Resultado final de um ciclo de corrente."""

    tensao: float
    corrente: float
    erro: bool


@dataclass(frozen=True)
class VpReading:
    """Decodificação de ENVIA_VARIAVEIS_GEO P1=0x31 (VP)."""

    vpeak: float
    vp_raw: int
    varvp: float
    varvp_raw: int
    n_pulsos: int
    ganho: int
    amostras: int


@dataclass(frozen=True)
class SpReading:
    """Decodificação de ENVIA_VARIAVEIS_GEO P1=0x32 (SP) — três amostras."""

    sp1: float
    sp2: float
    sp3: float


@dataclass(frozen=True)
class FullwaveReading:
    """Decodificação de ENVIA_VARIAVEIS_GEO P1=0x35 (Fullwave)."""

    samples: np.ndarray  # int32 array
    raw: bytes  # bytes brutos do payload (debug)


@dataclass(frozen=True)
class ContactResistanceReading:
    """Decodificação de ENVIA_RES_CONTATO."""

    resistencia: int  # ohms (já multiplicado por 2 como no switch.py legado)


# =============================================================================
# Erros
# =============================================================================


class ProtocolError(RuntimeError):
    """Não houve resposta válida após ``n_tries`` tentativas."""


# =============================================================================
# Cliente
# =============================================================================


class Central:
    """Cliente da DelfosCentralFT sobre um ``SerialTransport``-like.

    O argumento ``transport`` precisa expor: ``write(bytes)``, ``read(n)``,
    ``set_timeout(t)`` e o atributo ``timeout``. O ``SerialTransport`` deste
    pacote satisfaz; um fake de testes também (ver ``tests/conftest.py``).
    """

    def __init__(self, transport: Any, *, n_tries: int = 5):
        self.transport = transport
        self.n_tries = n_tries

    # ------------------------------------------------------------------ infra

    def _send_recv(self, frame: bytes, *, ans_length: int = 16) -> ResponseFrame:
        """Envia ``frame`` e lê ``ans_length`` bytes; faz até ``n_tries``
        tentativas se o eco não bater. Retorna o ResponseFrame parseado."""
        last_received = b""
        for _ in range(self.n_tries):
            self.transport.write(frame)
            received = self.transport.read(ans_length)
            last_received = received
            if self._echo_ok(frame, received):
                return ResponseFrame.parse(received)
        raise ProtocolError(
            f"Sem resposta válida após {self.n_tries} tentativas. "
            f"Enviado: {frame.hex()} (ans_length={ans_length}); "
            f"última leitura: {last_received.hex()}"
        )

    def _send_recv_raw(self, frame: bytes, *, ans_length: int) -> bytes:
        """Igual a ``_send_recv`` mas devolve bytes crus (resposta de tamanho
        variável que NÃO encaixa no layout padrão de 16 bytes)."""
        last_received = b""
        for _ in range(self.n_tries):
            self.transport.write(frame)
            received = self.transport.read(ans_length)
            last_received = received
            if self._echo_ok(frame, received):
                return received
        raise ProtocolError(
            f"Sem resposta válida após {self.n_tries} tentativas. "
            f"Enviado: {frame.hex()} (ans_length={ans_length}); "
            f"última leitura: {last_received.hex()}"
        )

    def _send_no_recv(self, frame: bytes) -> None:
        self.transport.write(frame)

    @staticmethod
    def _echo_ok(sent: bytes, received: bytes) -> bool:
        if len(received) < 4:
            return False
        if received[0] != SOF:
            return False
        # Eco: SOF + ADDH + ADDL + CMD devem casar com o que foi enviado.
        return received[0:4] == sent[0:4]

    # ------------------------------------------------------------ ping / addr

    def ping_central(self, reset_time: int = 48) -> ResponseFrame:
        """Ping na Central via ENVIA_ENDERECO em ADDR=0x0000.

        ``reset_time`` é P1 (multiplicador interno de timeout na Central).
        """
        frame = build_command_frame(
            addr=0x0000, cmd=Command.ENVIA_ENDERECO, p1=reset_time
        )
        return self._send_recv(frame)

    def ping_unit(self, addr: int) -> ResponseFrame:
        """Ping numa UASG. ``addr`` é o endereço de 16 bits (ADDH<<8 | ADDL)."""
        frame = build_command_frame(addr=addr, cmd=Command.ENVIA_ENDERECO)
        return self._send_recv(frame)

    # ------------------------------------------------------------------- ciclo

    def set_cycle(self, cycle: CyclePeriod | int) -> ResponseFrame:
        """SET_CYCLE_PERIOD ('B') broadcast — define multiplicador do PLL."""
        frame = build_command_frame(
            addr=BROADCAST_ADDR, cmd=Command.SET_CYCLE_PERIOD, p1=int(cycle)
        )
        return self._send_recv(frame)

    # --------------------------------------------------------- alimentação UASG

    def liga_alim_uasgs(self) -> ResponseFrame:
        """LIGA_ALIM_UASGS ('K')."""
        frame = build_command_frame(addr=0x0000, cmd=Command.LIGA_ALIM_UASGS)
        return self._send_recv(frame)

    def desliga_alim_uasgs(self) -> ResponseFrame:
        """DESLIGA_ALIM_UASGS ('Y')."""
        frame = build_command_frame(addr=0x0000, cmd=Command.DESLIGA_ALIM_UASGS)
        return self._send_recv(frame)

    # ----------------------------------------------------- transmissor (CDO 'U')

    def current_off(self) -> ResponseFrame:
        """Desliga o transmissor de corrente (P1=DESLIGA)."""
        return self._cdo_transmissor(CurrentControlMode.DESLIGA, p2=0, p3=0)

    def current_abort(self) -> ResponseFrame:
        """Aborta o transmissor (emergência)."""
        return self._cdo_transmissor(CurrentControlMode.ABORTA, p2=0, p3=0)

    def current_auto(self, corrente_ma: float) -> ResponseFrame:
        """Liga em modo controle de corrente. ``corrente_ma`` em mA, 10..1000."""
        p2 = self._encode_corrente_ma(corrente_ma)
        return self._cdo_transmissor(CurrentControlMode.LIGA_AUTO_AJUSTE, p2=p2, p3=0)

    def current_cycle_start(
        self,
        corrente_ma: float,
        *,
        stack: int = 5,
        turbo: bool = False,
    ) -> ResponseFrame:
        """Inicia ciclo de corrente. Equivalente a ``turn_current_ciclo`` envio.

        Use ``run_current_cycle`` para a operação completa (envio + leitura
        de amostras até count==0).
        """
        p1 = (
            CurrentControlMode.LIGA_TURBO
            if turbo
            else CurrentControlMode.LIGA_AUTO_AJUSTE
        )
        p2 = self._encode_corrente_ma(corrente_ma)
        return self._cdo_transmissor(p1, p2=p2, p3=stack)

    def current_change_on_fly(self, corrente_ma: float) -> ResponseFrame:
        """Muda a corrente sem desligar (requer sequenciamento ativo)."""
        p2 = self._encode_corrente_ma(corrente_ma)
        return self._cdo_transmissor(
            CurrentControlMode.MUDA_CORRENTE_ON_THE_FLY, p2=p2, p3=0
        )

    def current_sequence_start(
        self,
        pwm: int,
        *,
        cycle_type: CurrentCycleType = CurrentCycleType.UASGI_PULSOS_POS_NEG,
    ) -> ResponseFrame:
        """INICIA_SEQUENCIAMENTO. ``pwm`` em [0..MAX_POT_PWM=34]."""
        return self._cdo_transmissor(
            CurrentControlMode.INICIA_SEQUENCIAMENTO, p2=pwm, p3=int(cycle_type)
        )

    def _cdo_transmissor(
        self, p1: CurrentControlMode | int, *, p2: int, p3: int
    ) -> ResponseFrame:
        frame = build_command_frame(
            addr=0x0000,
            cmd=Command.CDO_TRANSMISSOR_CORRENTE,
            p1=int(p1),
            p2=p2,
            p3=p3,
        )
        return self._send_recv(frame)

    @staticmethod
    def _encode_corrente_ma(corrente_ma: float) -> int:
        """Corrente em mA → P2 do firmware (décimas, máx 100 ≡ 1000mA)."""
        v = round(corrente_ma / 10)
        if v > 100:
            v = 100
        if v < 0:
            v = 0
        return v

    # ----------------------------- ciclo de corrente: envio + leitura contínua

    def run_current_cycle(
        self,
        corrente_ma: float,
        *,
        stack: int = 5,
        turbo: bool = False,
        sample_timeout: float = 1.0,
        max_misses: int = 5,
    ) -> CurrentCycleResult:
        """Executa um ciclo de corrente completo.

        Equivalente ao ``turn_current_ciclo`` do switch.py: envia o comando 'U'
        e lê amostras de 16 bytes até receber ``count==0`` ou exceder
        ``max_misses`` leituras inválidas (nesse caso aborta com erro).

        O timeout do transporte é ajustado para ``sample_timeout`` durante o
        ciclo e restaurado ao final.
        """
        old_timeout = self.transport.timeout
        self.transport.set_timeout(sample_timeout)
        try:
            self.current_cycle_start(corrente_ma, stack=stack, turbo=turbo)
            tensao = 0.0
            corrente = 0.0
            misses = 0
            erro = False
            while True:
                received = self.transport.read(16)
                frame = self._strip_to_sof(received, min_len=14)
                if len(frame) >= 14:
                    misses = 0
                    tensao_raw = int.from_bytes(frame[4:8], "little", signed=False)
                    corrente_raw = int.from_bytes(frame[8:12], "little", signed=True)
                    tensao = convert_adc(tensao_raw, ADC_TENSAO)
                    corrente = abs(convert_adc(corrente_raw, ADC_CORRENTE))
                    count = frame[12]
                    if count == 0:
                        break
                else:
                    misses += 1
                    if misses > max_misses:
                        # Aborta o ciclo via STOP da medição geofísica VP.
                        self.stop_geo(GeoVariable.VP)
                        erro = True
                        break
            return CurrentCycleResult(tensao=tensao, corrente=corrente, erro=erro)
        finally:
            self.transport.set_timeout(old_timeout)

    @staticmethod
    def _strip_to_sof(data: bytes, *, min_len: int) -> bytes:
        """Procura ``0x7F`` e retorna o frame a partir dele, ou b'' se curto."""
        try:
            start = data.index(SOF)
        except ValueError:
            return b""
        frame = data[start:]
        if len(frame) < min_len:
            return b""
        return frame

    # ---------------------------------------------------- aquisição geofísica

    def start_geo(
        self,
        variable: GeoVariable | int,
        *,
        p2: int = 0,
        p3: int = 0,
    ) -> ResponseFrame:
        """INICIA_MEDE_GEOFISICA ('E') broadcast UASGi."""
        frame = build_command_frame(
            addr=addr_join(0xBF, 0x03),
            cmd=Command.INICIA_MEDE_GEOFISICA,
            p1=int(variable),
            p2=p2,
            p3=p3,
        )
        return self._send_recv(frame)

    def stop_geo(self, variable: GeoVariable | int) -> ResponseFrame:
        """PARA_MEDE_GEOFISICA ('F') broadcast UASGi."""
        frame = build_command_frame(
            addr=addr_join(0xBF, 0x03),
            cmd=Command.PARA_MEDE_GEOFISICA,
            p1=int(variable),
        )
        return self._send_recv(frame)

    # -------------------------------------------------- upload de variáveis (G)

    def read_vp(self, addr: int, *, _retried: bool = False) -> VpReading:
        """ENVIA_VARIAVEIS_GEO P1=VP. Resposta de 28 bytes.

        Se as três amostras de VP no frame discordam (qtd==1), refaz uma vez —
        comportamento herdado do switch.py.
        """
        frame = build_command_frame(
            addr=addr, cmd=Command.ENVIA_VARIAVEIS_GEO, p1=int(GeoVariable.VP)
        )
        data = self._send_recv_raw(frame, ans_length=28)
        if len(data) < 28:
            return VpReading(0.0, 0, 0.0, 0, 0, 0, 0)
        vp0_raw = int.from_bytes(data[11:15], "little", signed=True)
        vp1_raw = int.from_bytes(data[15:19], "little", signed=True)
        vp2_raw = int.from_bytes(data[23:27], "little", signed=True)
        vp_raw, qtd = Counter([vp0_raw, vp1_raw, vp2_raw]).most_common(1)[0]
        vpeak = convert_adc(vp_raw, ADC_VP)
        varvp_raw = int.from_bytes(data[19:23], "little", signed=True)
        varvp = convert_adc(varvp_raw, ADC_VARVP)
        n_pulsos = data[4]
        ganho = data[7]
        # Nota: amostras compartilha bytes com vp2 — interpretação herdada do
        # switch.py legado. Não foi confirmado contra firmware.
        amostras = int.from_bytes(data[23:26], "little", signed=True)
        if qtd == 1 and not _retried:
            return self.read_vp(addr, _retried=True)
        return VpReading(
            vpeak=vpeak,
            vp_raw=vp_raw,
            varvp=varvp,
            varvp_raw=varvp_raw,
            n_pulsos=n_pulsos,
            ganho=ganho,
            amostras=amostras,
        )

    def read_sp(self, addr: int) -> SpReading:
        """ENVIA_VARIAVEIS_GEO P1=SP. Três amostras."""
        frame = build_command_frame(
            addr=addr, cmd=Command.ENVIA_VARIAVEIS_GEO, p1=int(GeoVariable.SP)
        )
        data = self._send_recv_raw(frame, ans_length=27)
        sp_raw1 = int.from_bytes(data[11:15], "little", signed=True)
        sp_raw2 = int.from_bytes(data[15:19], "little", signed=True)
        sp_raw3 = int.from_bytes(data[19:23], "little", signed=True)
        return SpReading(
            sp1=convert_adc(sp_raw1, ADC_SP),
            sp2=convert_adc(sp_raw2, ADC_SP),
            sp3=convert_adc(sp_raw3, ADC_SP),
        )

    def read_fullwave(self, addr: int, *, read_timeout: float = 2.0) -> FullwaveReading:
        """ENVIA_VARIAVEIS_GEO P1=FULLWAVE.

        Resposta variável: cabeçalho de 13 bytes traz ``tamanho_frame`` em
        bytes 11-12 (little-endian). Lemos ``tamanho_frame - 16`` bytes
        adicionais e os interpretamos como int32.

        ``read_timeout`` é aplicado durante a leitura do payload (default 2s,
        igual ao switch.py); o timeout original do transporte é restaurado
        ao final.
        """
        frame = build_command_frame(
            addr=addr, cmd=Command.ENVIA_VARIAVEIS_GEO, p1=int(GeoVariable.FULLWAVE)
        )
        old_timeout = self.transport.timeout
        self.transport.set_timeout(read_timeout)
        try:
            header = self._send_recv_raw(frame, ans_length=13)
            tamanho_frame = int.from_bytes(header[11:13], "little", signed=False)
            data_full = self.transport.read(tamanho_frame - 16)
            r = len(data_full) // 4
            samples = np.frombuffer(data_full[: r * 4], dtype=np.int32)
            return FullwaveReading(samples=samples, raw=bytes(data_full))
        finally:
            self.transport.set_timeout(old_timeout)

    # ------------------------------------------------- conexão de eletrodos (R)

    def set_electrodes(
        self,
        addr: int,
        electrodes: list[int],
        *,
        line: int = 1,
    ) -> ResponseFrame:
        """CONEX_ELETRODO em modo MR64 (frame longo de 18 bytes).

        ``electrodes`` é uma lista de 11 inteiros: ``[I+, I-, S0..S8]`` onde
        cada item é 0..31 ou 0xFF (255) para "não conectado".
        """
        if len(electrodes) != 11:
            raise ValueError(
                f"electrodes precisa ter 11 itens (I+, I-, S0..S8); recebido {len(electrodes)}"
            )
        if not 0 <= line <= 7:
            raise ValueError(f"line={line} fora do range 0..7")
        i_plus, i_minus, *signal = electrodes  # signal tem 9 itens
        extras = bytes(signal + [line, 0])  # 9 + 2 = 11 bytes
        frame = build_command_frame(
            addr=addr,
            cmd=Command.CONEX_ELETRODO,
            p1=0xAA,  # sub-comando MR64 "conecta"
            p2=i_plus,
            p3=i_minus,
            extras=extras,
        )
        return self._send_recv(frame)

    def clear_electrodes(self, addr: int) -> ResponseFrame:
        """Desconecta todos os eletrodos (modo Delfos UASG, broadcast=ok)."""
        frame = build_command_frame(
            addr=addr,
            cmd=Command.CONEX_ELETRODO,
            p1=int(ElectrodeMode.DESCONECTA),
            p2=int(ElectrodeMode.DESCONECTA),
            p3=int(ElectrodeE3Mode.NORMAL),
        )
        return self._send_recv(frame)

    # ------------------------------------------- resistência de contato (C, D)

    def measure_contact_resistance(self, *, even: bool = True) -> ResponseFrame:
        """RESIST_CONTATO ('C') broadcast UASGi par (0xBF, 0x01) ou ímpar (0xBF, 0x00)."""
        addl = 0x01 if even else 0x00
        frame = build_command_frame(
            addr=addr_join(0xBF, addl),
            cmd=Command.RESIST_CONTATO,
        )
        return self._send_recv(frame)

    def read_contact_resistance(self, addr: int) -> ContactResistanceReading:
        """ENVIA_RES_CONTATO ('D') — devolve ohms (×2 como no switch.py)."""
        frame = build_command_frame(addr=addr, cmd=Command.ENVIA_RES_CONTATO)
        resp = self._send_recv(frame, ans_length=16)
        res = int.from_bytes(resp.raw[4:6], "little", signed=False)
        return ContactResistanceReading(resistencia=res * 2)

    # ----------------------------------------------- corrente (informação - S)

    def read_current(self) -> CurrentReading:
        """INF_CORRENTE_TRANSM ('S') — corrente do shunt."""
        frame = build_command_frame(addr=0x0000, cmd=Command.INF_CORRENTE_TRANSM)
        resp = self._send_recv(frame, ans_length=16)
        tensao_raw = int.from_bytes(resp.raw[4:8], "little", signed=False)
        corrente_raw = int.from_bytes(resp.raw[8:12], "little", signed=True)
        return CurrentReading(
            tensao=convert_adc(tensao_raw, ADC_TENSAO),
            corrente=abs(convert_adc(corrente_raw, ADC_CORRENTE)),
            tensao_raw=tensao_raw,
            corrente_raw=corrente_raw,
            raw=resp.raw,
        )

    def measure_contact_resistance_pulse(
        self,
        *,
        current_pwm: int = 0,
        settle_timeout: float = 0.6,
    ) -> CurrentReading:
        """Inicia uma medida de resistência de contato pelo transmissor da Central
        (CDO_TRANSMISSOR_CORRENTE com P1=MEDE_RESISTENCIA) e devolve a leitura
        que segue o ACK (segundo frame, com tensão/corrente).

        Equivale ao padrão do ``res_contato`` do switch.py legado: enviar 0x55
        P1=0x31 e fazer ``read(16)`` extra após o ACK.
        """
        self._cdo_transmissor(
            CurrentControlMode.MEDE_RESISTENCIA, p2=current_pwm, p3=0
        )
        old_timeout = self.transport.timeout
        self.transport.set_timeout(settle_timeout)
        try:
            data = self.transport.read(16)
        finally:
            self.transport.set_timeout(old_timeout)
        frame = self._strip_to_sof(data, min_len=12)
        if len(frame) < 12:
            raise ProtocolError(
                f"Leitura curta após MEDE_RESISTENCIA: {data.hex()}"
            )
        tensao_raw = int.from_bytes(frame[4:8], "little", signed=False)
        corrente_raw = int.from_bytes(frame[8:12], "little", signed=True)
        return CurrentReading(
            tensao=convert_adc(tensao_raw, ADC_TENSAO),
            corrente=abs(convert_adc(corrente_raw, ADC_CORRENTE)),
            tensao_raw=tensao_raw,
            corrente_raw=corrente_raw,
            raw=bytes(frame[:16]),
        )

    # ---------------------------------------------- registro sísmico ('J') — só
    # API mínima exposta para diagnose; sismica completa fica fora do escopo
    # (ver CLAUDE.md). Mantido aqui para acesso de baixo nível, sem orquestração.

    def sismica_state(
        self,
        state: SismicState | int,
        *,
        threshold_mult: int = 0,
        sample_rate: int = 125,
    ) -> ResponseFrame:
        """REGISTRA_SISMICA ('J'). Use só para diagnose — orquestração sísmica
        não faz parte deste pacote."""
        frame = build_command_frame(
            addr=addr_join(0xBF, 0x03),
            cmd=Command.REGISTRA_SISMICA,
            p1=int(state),
            p2=threshold_mult,
            p3=sample_rate,
        )
        return self._send_recv(frame)
