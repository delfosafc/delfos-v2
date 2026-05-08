"""Protocolo de comunicação Console <-> Central Delfos.

Catálogo dos comandos, parâmetros, estados e códigos de resposta extraídos
diretamente do firmware da DelfosCentralFT (não do header desatualizado
DefinicoesGeraisDelfos.h).

Fontes principais no firmware:
- DelfosCentralFT/ProtocoloTxCentral.c — switch principal de comandos
- DelfosCentralFT/MontaFrameTxCentral.c — parser do frame Console -> Central
- DelfosCentralFT/CtrlFonteCor_Ciclo.c   — layout do frame Central -> Console
- DelfosCentralFT/DelfosCentralFunctions.c — algoritmo de CRC

Frame format:
    Console -> Central (sem CRC):
        [0x7F][ADDH][ADDL][CMD][P1][P2][P3]              = 7 bytes  (UASG)
        [0x7F][ADDH][ADDL][0x52][P1>=0x55][...13 bytes]  = 18 bytes (MR64)

    Central -> Console (sem CRC, 16 bytes):
        [0x7F][ADDH][ADDL][CMD echo]
        [4 bytes payload/eco]
        [StatusCorrente][StatusGeral][StatusGeral1]
        [sw_version][SystemState][ResponseCode][2 bytes pad]

    RS485 Central <-> UASG (com CRC CCITT — não é o caminho do console):
        Frame regular + 2 bytes CRC16 (poly 0x1021, init 0xFFFF, MSB first).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum, IntFlag

# =============================================================================
# CONSTANTES DE FRAME
# =============================================================================

SOF = 0x7F
# Tamanho da struct UCToConsoleTrxData no firmware: 16 bytes. Os 2 últimos
# (14-15) são pad e a Central frequentemente emite só os 14 primeiros.
RESPONSE_FRAME_SIZE = 16
RESPONSE_FRAME_MIN_SIZE = 14
COMMAND_FRAME_SIZE_UASG = 7
# 19 bytes = 7 (header) + 11 extras + 1 pad final que o firmware ignora
# mas o transmissor emite por convenção.
COMMAND_FRAME_SIZE_MR64 = 19

BROADCAST_ADDR_HIGH = 0xFF
BROADCAST_ADDR_LOW = 0xFD
BROADCAST_ADDR = (BROADCAST_ADDR_HIGH << 8) | BROADCAST_ADDR_LOW  # 0xFFFD


# =============================================================================
# COMANDOS (opcodes aceitos pela Central)
# =============================================================================


class Command(IntEnum):
    """Opcodes que a DelfosCentralFT aceita do console.

    Lista extraída do switch em ProtocoloTxCentral.c:203. Qualquer opcode
    fora desta lista retorna ResponseCode.COMANDO_INDEFINIDO.
    """

    # "A" — solicita endereço da unidade. Quando ADDH=0 e ADDL=0, é ping na Central.
    # Caso contrário liga alimentação das UASGs e encaminha para a remota indicada.
    ENVIA_ENDERECO = 0x41

    # "B" — define multiplicador do PLL (período do ciclo IP). Broadcast.
    SET_CYCLE_PERIOD = 0x42

    # "C" — inicia medida de resistência de contato dos eletrodos.
    RESIST_CONTATO = 0x43

    # "D" — solicita o valor da resistência de contato medida.
    ENVIA_RES_CONTATO = 0x44

    # "E" — inicia registro/aquisição da variável geofísica selecionada.
    INICIA_MEDE_GEOFISICA = 0x45

    # "F" — encerra o registro da variável geofísica.
    PARA_MEDE_GEOFISICA = 0x46

    # "G" — solicita upload das amostras adquiridas.
    ENVIA_VARIAVEIS_GEO = 0x47

    # "J" — controla o registro sísmico (start/stop/upload de buffer).
    REGISTRA_SISMICA = 0x4A

    # "K" — liga a alimentação das UASGs Delfos. (No header conflita com
    # SendBurst, mas na Central é LigaAlimUASGs que ganha.)
    LIGA_ALIM_UASGS = 0x4B

    # "6" — comando NOVO no firmware, ainda sem #define no header.
    # Mede resistência de contato pelo transmissor da Central com perfil similar
    # ao 0x55 P1=0x31 (RM1RM64=0xA2, modo turbo desligado). Ver
    # ProtocoloTxCentral.c:968.
    MEDE_RES_CONTATO_TURBO = 0x36

    # "Q" — define a ordem de repetição (1..9) da unidade endereçada.
    DEFINE_REPETIDOR = 0x51

    # "R" — comanda conexão dos eletrodos de corrente. Frame curto para Delfos
    # UASG (P1<0x55) ou frame longo para MR64 (P1>=0x55).
    CONEX_ELETRODO = 0x52

    # "S" — solicita corrente do shunt. A Central também emite este frame
    # autonomamente a cada ciclo IP on (ver CtrlFonteCor_Ciclo.c).
    INF_CORRENTE_TRANSM = 0x53

    # "U" — controla o transmissor de corrente local da Central (liga/desliga,
    # mede resistência, sequenciamento, modo turbo, muda corrente on-the-fly).
    CDO_TRANSMISSOR_CORRENTE = 0x55

    # "W" — ping na Central. Se P1!=0xFF altera o multiplicador do timeout
    # de comunicação (TempoEsperaCommPC).
    PING_CENTRAL = 0x57

    # "Y" — desliga a alimentação das UASGs. (No header conflita com GoSleep,
    # mas na Central é DesligaAlimUASGs que ganha.)
    DESLIGA_ALIM_UASGS = 0x59


class LegacyCommand(IntEnum):
    """Comandos suportados pela UASG mas DESATIVADOS na Central.

    Estão presentes no firmware da remota (ExecutaComandoDelfos.c) mas a
    Central não tem `case` ativo — o trecho está dentro de um bloco /* ... */
    em ProtocoloTxCentral.c (~linha 672). Mantidos aqui para o caso de
    voltarem a ser ativados.
    """

    SENTIU_CORRENTE = 0x48  # "H" — broadcast com resposta de quem sentiu corrente vizinha
    CORRENTE_MATRIX_ID = 0x49  # "I" — aplica corrente para identificação da matriz
    MATRIX_ID = 0x4D  # "M" — entra em modo identificação da matriz


# =============================================================================
# ENUMS DE PARÂMETROS
# =============================================================================


class CyclePeriod(IntEnum):
    """Parâmetro 1 de SET_CYCLE_PERIOD — multiplicador do PLL.

    Cada caso atribui IncPLLIp = IncPLLIpBase32 * N, definindo a frequência
    do ciclo IP. Os valores estão em ASCII porque o protocolo trafega bytes
    imprimíveis.
    """

    CYCLE_8S_PULSE_2S = 0x31  # mult=1
    CYCLE_4S_PULSE_1S = 0x32  # mult=2
    CYCLE_2S_PULSE_500MS = 0x34  # mult=4
    CYCLE_1_33S_PULSE_333MS = 0x36  # mult=6
    CYCLE_1_33S_PULSE_333MS_ALT = 0x37  # idêntico a 0x36 no código
    CYCLE_1S_PULSE_250MS = 0x38  # mult=8
    CYCLE_500MS_PULSE_125MS = 0x39  # mult=16


class GeoVariable(IntEnum):
    """Variável geofísica para INICIA/PARA/ENVIA_VARIAVEIS_GEO (P1)."""

    IP_VP = 0x30
    VP = 0x31
    SP = 0x32
    SISMICA_GEOFONE_1_3 = 0x33
    # Nota: SISMICA_GEOFONE_2_4 (0x34) está comentado no INICIA_MEDE_GEOFISICA
    # mas continua aceito em PARA_MEDE_GEOFISICA e ENVIA_VARIAVEIS_GEO.
    SISMICA_GEOFONE_2_4 = 0x34
    FULLWAVE = 0x35  # só ENVIA_VARIAVEIS_GEO


class SismicState(IntEnum):
    """Estado de registro sísmico (P1 de REGISTRA_SISMICA)."""

    CONTINUO = 0x30  # registro circular contínuo no buffer
    POS = 0x31  # registra um buffer e para
    MEIO = 0x32  # registra meio buffer
    MEIO_PSEUDO_ATIVO = 0x33  # registra ao detectar evento sísmico (geofone sentinela)
    IDLE = 0x34
    SENDING = 0x35  # comando para enviar buffer registrado
    SAI_MEDE_SISMICA = 0x37  # sai do modo sísmica


class SeismicSampleRate(IntEnum):
    """Constante de taxa de amostragem (P3 de REGISTRA_SISMICA)."""

    SR_124 = 124
    SR_125 = 125  # default
    SR_126 = 126
    SR_127 = 127


class ElectrodeMode(IntEnum):
    """Modo dos eletrodos 1 e 2 (P1, P2 de CONEX_ELETRODO em modo Delfos UASG).

    Define a relação entre o eletrodo e a polaridade da corrente A ou B durante
    o ciclo do PLL. Veja comentário no firmware em DefinicoesGeraisDelfos.h:108.
    """

    DESCONECTA = 0x30  # mede sinal — relé e FET desligados
    CORRENTE_A = 0x31  # corrente positiva no 1º quarto do ciclo, negativa no 3º
    CORRENTE_B = 0x32  # corrente negativa no 1º quarto do ciclo, positiva no 3º


class ElectrodeE3Mode(IntEnum):
    """Modo do eletrodo 3 (P3 de CONEX_ELETRODO)."""

    NORMAL = 0x30
    DESCONECTA = 0x33  # relé liga, desconecta entrada do ADC do eletrodo


class CurrentControlMode(IntEnum):
    """P1 de CDO_TRANSMISSOR_CORRENTE — comanda o transmissor da Central."""

    DESLIGA = 0x30
    MEDE_RESISTENCIA = 0x31  # liga para medir resistência dos eletrodos
    ABORTA = 0x32  # emergência — desliga sem ajuste
    LIGA_AUTO_AJUSTE = 0x33  # modo controle de corrente
    INICIA_SEQUENCIAMENTO = 0x34  # inicia ciclo de corrente
    MUDA_CORRENTE_ON_THE_FLY = 0x35  # muda corrente sem desligar (requer sequenciamento ativo)
    LIGA_TURBO = 0x37  # modo turbo (sem tempo off entre pulsos)


class CurrentCycleType(IntEnum):
    """P3 de CDO_TRANSMISSOR_CORRENTE quando P1=INICIA_SEQUENCIAMENTO (0x34).

    Define o tipo de ciclo de corrente. Internamente vira a flag RM1RM64.
    """

    UASG_PULSOS_POSITIVOS = 0  # 0xA0 — só pulsos positivos
    UASGI_PULSOS_POS_NEG = 1  # 0xA1 — pulsos positivos e negativos
    UASGI_PULSOS_POS_NEG_SEM_OFF = 2  # 0xA2 — sem tempo off entre pulsos


# Limite máximo da programação de PWM (parâmetro de potência) — vide MaxPot
# em DefinicoesGeraisDelfos.h:382.
MAX_POT_PWM = 34


# =============================================================================
# ESTADOS DO SISTEMA
# =============================================================================


class SystemState(IntEnum):
    """Estado interno da Central (echoed no byte 12 do frame de resposta)."""

    IDLE = 0x00
    TRIP_ON = 0x01  # transmissor IP on, sincroniza ciclo (envia beacon)
    MEDINDO_IP = 0x02
    PRE_MEDINDO_IP = 0x03
    MED_RES_CONT_0 = 0x04  # medindo resistência de contato dipolo 0
    MED_RES_CONT_1 = 0x05  # dipolo 1
    DESLIGANDO_MEDE_IP = 0x06
    MED_RES_CONTATO = 0x07  # remota mede resistência
    UPLOADING = 0x08
    FINAL_UPLOADING = 0x09
    ETERNAL_BURST = 0x0B
    SAI_ETERNAL_BURST = 0x0C
    ID_MATRIX = 0x20  # identificando posição em campo
    ZERA_OFFSET_ADC = 0x80
    ANALISE_ADC = 0x81
    POTENCIAL_ELETRODO = 0x82
    MEDINDO_SP = 0xA0
    IDLE_SISMICA = 0xB0  # 0xBx = grupo sísmica
    MEDINDO_MASW_13 = 0xB1
    MEDINDO_MASW_24 = 0xB2
    MEDINDO_SISMICA_PASSIVA = 0xB3
    UPLOADING_VAR_GEO = 0xD0
    DEBUGING_ADC = 0xDF


GRUPO_SISMICA_MASK = 0xF0
GRUPO_SISMICA_VALUE = 0xB0  # (state & 0xF0) == 0xB0 indica modo sísmica


class StatusGeral(IntFlag):
    """Bits do byte StatusGeral (echoed no byte 9 da resposta).

    Bits 6-7 são nível de rejeição de stack — não usado em Delfos.
    """

    CORRENTE_IP_ON = 0x01
    MED_GEO_ON = 0x02  # também usado como MED_IP_ON (mesmo bit)
    MED_RES_ON = 0x04
    TOPOLOGIA_ON = 0x08
    ID_MATRIX_ON = 0x10
    WAKING_UP_ON = 0x20


# Alias semântico — o firmware usa os dois nomes para o mesmo bit
StatusGeral.MED_IP_ON = StatusGeral.MED_GEO_ON  # type: ignore[attr-defined]


class StatusGeral1(IntFlag):
    """Bits do byte StatusGeral1 (echoed no byte 10 da resposta)."""

    VP = 0x01  # medindo potencial primário
    SP = 0x02  # medindo potencial espontâneo
    SISM_SET_0 = 0x04  # MASW conjunto de geofones 0
    MODO_SISMICA_0 = 0x08
    MODO_SISMICA_1 = 0x10
    REG_SISMICA = 0x20  # registrando amostras de sísmica
    REG_SISM_PSEUDO_ATV = 0x40  # capturando sísmica (gatilho disparado)
    SISM_PSEUDO_ENGATILHADA = 0x80  # geofone sentinela armado


# =============================================================================
# CÓDIGOS DE RESPOSTA (byte 13 do frame Central -> Console)
# =============================================================================


class ResponseCode(IntEnum):
    """Códigos no byte 13 da resposta — interpretação do resultado do comando."""

    INDEFINIDO = 0x30
    MEDIDA_EM_ANDAMENTO = 0x31
    FORA_ESTADO_PERMITIDO = 0x32  # comando incompatível com SystemState atual
    CORRENTE_LIGADA = 0x33  # comando só permitido com corrente off
    CORRENTE_DESLIGADA = 0x34  # comando só permitido com corrente on
    COMANDO_INDEFINIDO = 0x36  # opcode desconhecido na Central
    PARAMETRO_INDEFINIDO = 0x37
    OUT_OF_RANGE = 0x38  # parâmetro fora do range aceito
    CAPT_SISMICA_ON = 0x39
    INICIANDO_CENTRAL = 0x40  # enviado após reset da Central
    NP_PERMITIDO_BROADCAST = 0x61  # parâmetro inválido em broadcast
    CENTRAL_RESPONDE = 0x62  # ACK — comando aceito
    CORRENTE_CONVERGINDO = 0x63  # esperando convergir medida de corrente
    ELETRODO_COR_ABERTO = 0x64
    PONTE_H_LADO_ABERTO = 0x65  # desbalanço entre ciclos da corrente


# =============================================================================
# ESPECIFICAÇÕES DE COMANDO (validação de parâmetros)
# =============================================================================


@dataclass(frozen=True)
class CommandSpec:
    """Define o que cada comando aceita como parâmetro válido.

    Um valor None em pN_valido significa "não validado" (qualquer byte).
    """

    code: Command
    descricao: str
    p1_valido: frozenset[int] | None = None
    p2_valido: frozenset[int] | None = None
    p3_valido: frozenset[int] | None = None
    aceita_broadcast: bool = True
    notas: str = ""


def _vals(enum_cls: type[IntEnum]) -> frozenset[int]:
    return frozenset(int(m) for m in enum_cls)


COMMAND_SPECS: dict[Command, CommandSpec] = {
    Command.ENVIA_ENDERECO: CommandSpec(
        code=Command.ENVIA_ENDERECO,
        descricao="Solicita endereço/liga UASGs. ADD=0,0 vira ping na Central.",
        notas="Só permitido se SystemState=IDLE ou em IDLE_SISMICA com EstadoSismica2=IDLE.",
    ),
    Command.SET_CYCLE_PERIOD: CommandSpec(
        code=Command.SET_CYCLE_PERIOD,
        descricao="Define multiplicador do PLL (período do ciclo IP).",
        p1_valido=_vals(CyclePeriod),
        notas="Só permitido em SystemState=IDLE.",
    ),
    Command.RESIST_CONTATO: CommandSpec(
        code=Command.RESIST_CONTATO,
        descricao="Inicia medida de resistência de contato.",
        notas="Só permitido em SystemState=IDLE. Se broadcast, sem resposta.",
    ),
    Command.ENVIA_RES_CONTATO: CommandSpec(
        code=Command.ENVIA_RES_CONTATO,
        descricao="Solicita o valor da resistência de contato medida.",
    ),
    Command.INICIA_MEDE_GEOFISICA: CommandSpec(
        code=Command.INICIA_MEDE_GEOFISICA,
        descricao="Inicia aquisição da variável geofísica selecionada.",
        # Note: 0x34 (SISMICA_24) está comentado no firmware — só 0x30..0x33.
        p1_valido=frozenset({0x30, 0x31, 0x32, 0x33}),
        notas=(
            "P2 (broadcast em sísmica): IndSizeBufferSis = P2 & 0x3C. "
            "P3: BufferFraction = P3 & 0x0F. "
            "IP/VP requer SystemState=TRIP_ON ou MEDINDO_IP. "
            "SP requer SystemState=IDLE."
        ),
    ),
    Command.PARA_MEDE_GEOFISICA: CommandSpec(
        code=Command.PARA_MEDE_GEOFISICA,
        descricao="Encerra registro de variável geofísica e retorna a IDLE.",
        notas="Broadcast — não tem resposta direta da Central.",
    ),
    Command.ENVIA_VARIAVEIS_GEO: CommandSpec(
        code=Command.ENVIA_VARIAVEIS_GEO,
        descricao="Solicita upload das amostras adquiridas.",
        # 0x34 está comentado — só aceita 0x30,0x31,0x32,0x33,0x35
        p1_valido=frozenset({0x30, 0x31, 0x32, 0x33, 0x35}),
        notas="Só permitido em IDLE, UPLOADING ou EstadoSismica1=IDLE.",
    ),
    Command.REGISTRA_SISMICA: CommandSpec(
        code=Command.REGISTRA_SISMICA,
        descricao="Controla o registro sísmico (start/stop/upload).",
        p1_valido=frozenset({0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x37}),
        p3_valido=frozenset({124, 125, 126, 127}),
        notas=(
            "Só permitido em modo sísmica ((SystemState & 0xF0) == 0xB0). "
            "P1=MEIO_PSEUDO_ATIVO usa P2 como multiplicador do threshold "
            "(P2=0 vira Vi1mv/4)."
        ),
    ),
    Command.LIGA_ALIM_UASGS: CommandSpec(
        code=Command.LIGA_ALIM_UASGS,
        descricao="Liga a alimentação das UASGs Delfos.",
    ),
    Command.MEDE_RES_CONTATO_TURBO: CommandSpec(
        code=Command.MEDE_RES_CONTATO_TURBO,
        descricao=(
            "Comando novo (sem #define no header). Mede resistência via transmissor "
            "da Central, modo UASGi."
        ),
        notas="P3=programação do PWM (deve ser <= MAX_POT_PWM=34).",
    ),
    Command.DEFINE_REPETIDOR: CommandSpec(
        code=Command.DEFINE_REPETIDOR,
        descricao="Define a ordem de repetição (1..9) da unidade endereçada.",
        p1_valido=frozenset(range(0x30, 0x39)),
        notas="Só permitido em SystemState=IDLE.",
    ),
    Command.CONEX_ELETRODO: CommandSpec(
        code=Command.CONEX_ELETRODO,
        descricao=(
            "Conecta eletrodos de corrente. Frame curto para Delfos UASG (P1<0x55) "
            "ou frame longo para MR64 (P1>=0x55, 18 bytes total)."
        ),
        notas=(
            "UASG: P1=eletrodo1, P2=eletrodo2 (ElectrodeMode), P3=eletrodo3 (ElectrodeE3Mode). "
            "Em broadcast só aceita P1=P2=P3=0x30 (limpa todos)."
        ),
    ),
    Command.INF_CORRENTE_TRANSM: CommandSpec(
        code=Command.INF_CORRENTE_TRANSM,
        descricao=(
            "Solicita corrente do shunt. Também é emitido autonomamente pela Central "
            "a cada ciclo IP on."
        ),
        notas=(
            "Resposta tem 4 bytes de corrente IP nas posições 4..7 e 4 bytes de "
            "corrente média em 8..11."
        ),
    ),
    Command.CDO_TRANSMISSOR_CORRENTE: CommandSpec(
        code=Command.CDO_TRANSMISSOR_CORRENTE,
        descricao="Controla o transmissor de corrente da Central (liga/desliga/modo).",
        p1_valido=_vals(CurrentControlMode),
        notas=(
            "P2: programação do PWM (potência) — limite MAX_POT_PWM=34. "
            "Em modos turbo/auto-ajuste P2 é corrente em décimas (10..1000mA = 1..100). "
            "P3: tipo de ciclo (CurrentCycleType) quando P1=INICIA_SEQUENCIAMENTO; "
            "número de ciclos para empilhamento quando P1=LIGA_TURBO/AUTO_AJUSTE."
        ),
    ),
    Command.PING_CENTRAL: CommandSpec(
        code=Command.PING_CENTRAL,
        descricao="Ping na Central. P1 ajusta multiplicador do timeout de comunicação.",
        notas="P1=0xFF mantém o timeout default (multiplicador=0xFE).",
    ),
    Command.DESLIGA_ALIM_UASGS: CommandSpec(
        code=Command.DESLIGA_ALIM_UASGS,
        descricao="Desliga a alimentação das UASGs Delfos.",
    ),
}


# =============================================================================
# CRC16 CCITT (poly 0x1021, init 0xFFFF, MSB first)
# =============================================================================

_CRC16_POLY = 0x1021


def crc16_ccitt(data: bytes | Iterable[int]) -> int:
    """Calcula CRC16 CCITT-FALSE como em DelfosCentralFunctions.c:390.

    Init=0xFFFF, polinômio 0x1021, MSB first, sem refletir, sem XOR final.

    Usado no enlace RS485 entre Central e UASG. NÃO é usado no enlace
    Console <-> Central — o protocolo do console não tem CRC.
    """
    crc = 0xFFFF
    for byte in data:
        for _bit in range(8):
            if ((crc & 0x8000) >> 8) ^ (byte & 0x80):
                crc = ((crc << 1) ^ _CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
            byte = (byte << 1) & 0xFF
    return crc


# =============================================================================
# FRAME BUILDER — Console -> Central
# =============================================================================


def _validate_param(spec_set: frozenset[int] | None, value: int, name: str, cmd: Command) -> None:
    if spec_set is None:
        return
    if value not in spec_set:
        accepted = ", ".join(f"0x{v:02X}" for v in sorted(spec_set))
        raise ValueError(
            f"{name}=0x{value:02X} inválido para {cmd.name}. Valores aceitos: {accepted}"
        )


def build_command_frame(
    addr: int,
    cmd: Command,
    p1: int = 0x00,
    p2: int = 0x00,
    p3: int = 0x00,
    extras: bytes = b"",
) -> bytes:
    """Monta um frame de comando do console para a Central.

    Args:
        addr: endereço da unidade alvo (16 bits). Use BROADCAST_ADDR para broadcast.
        cmd: opcode do comando (Command enum).
        p1, p2, p3: parâmetros (bytes). Validados contra COMMAND_SPECS quando há spec.
        extras: bytes adicionais para frames MR64 (CONEX_ELETRODO com p1>=0x55).
                Devem incluir os bytes 6..16 do frame (S0..S8 + selecLinha + ...).

    Returns:
        Bytes prontos para enviar pela UART (começa com SOF=0x7F).

    Raises:
        ValueError: se algum parâmetro estiver fora do conjunto aceito pela
                    especificação do comando.
    """
    if not 0 <= addr <= 0xFFFF:
        raise ValueError(f"addr=0x{addr:04X} fora do range 0x0000..0xFFFF")
    for name, val in (("p1", p1), ("p2", p2), ("p3", p3)):
        if not 0 <= val <= 0xFF:
            raise ValueError(f"{name}=0x{val:X} fora do range 0x00..0xFF")

    spec = COMMAND_SPECS.get(cmd)
    if spec is not None:
        _validate_param(spec.p1_valido, p1, "p1", cmd)
        _validate_param(spec.p2_valido, p2, "p2", cmd)
        _validate_param(spec.p3_valido, p3, "p3", cmd)
        is_broadcast = (addr >> 8) == BROADCAST_ADDR_HIGH and (addr & 0xFF) == BROADCAST_ADDR_LOW
        if is_broadcast and not spec.aceita_broadcast:
            raise ValueError(f"{cmd.name} não aceita broadcast")

    addh = (addr >> 8) & 0xFF
    addl = addr & 0xFF

    is_mr64 = cmd == Command.CONEX_ELETRODO and p1 >= 0x55
    if is_mr64:
        # Frame de 19 bytes: 7 header + 11 extras + 1 pad final.
        if len(extras) != 11:
            raise ValueError(
                f"Frame MR64 (CONEX_ELETRODO p1>=0x55) precisa de exatamente 11 bytes "
                f"em extras (S0..S8 + 2 vagos), recebido {len(extras)}"
            )
        return bytes([SOF, addh, addl, int(cmd), p1, p2, p3]) + extras + b"\x00"

    if extras:
        raise ValueError("extras só é válido em frame MR64 (CONEX_ELETRODO p1>=0x55)")

    return bytes([SOF, addh, addl, int(cmd), p1, p2, p3])


# =============================================================================
# FRAME PARSER — Central -> Console
# =============================================================================


@dataclass
class ResponseFrame:
    """Frame de 16 bytes que a Central manda para o console.

    Layout (UCToConsoleTrxData):
        [0]      SOF (0x7F)
        [1-2]    Endereço UASG (eco)
        [3]      Comando (eco do CMD recebido, ou 0x53 se for InfCorrenteTransm autônomo)
        [4-7]    Payload de 4 bytes — em respostas a comando: bytes 4-5 ecoam P1,P2 e
                 bytes 6-7 ficam com erro/status. Em InfCorrenteTransm autônomo,
                 são 4 bytes da corrente IP instantânea.
        [8]      StatusCorrente (em InfCorrenteTransm: byte 0 da corrente média)
        [9]      StatusGeral
        [10]     StatusGeral1
        [11]     sw_version (em InfCorrenteTransm: byte 3 da corrente média)
        [12]     SystemState (em InfCorrenteTransm: SobretensaoFonteCorrente)
        [13]     ResponseCode / argmto
        [14-15]  pad
    """

    addr: int
    cmd: int  # int e não Command para sobreviver a opcodes novos
    payload: bytes  # bytes 4..7
    status_corrente: int
    status_geral: StatusGeral
    status_geral1: StatusGeral1
    sw_version: int
    system_state_raw: int  # int para sobreviver a estados novos
    error_raw: int
    raw: bytes

    @property
    def cmd_enum(self) -> Command | None:
        try:
            return Command(self.cmd)
        except ValueError:
            return None

    @property
    def system_state(self) -> SystemState | None:
        try:
            return SystemState(self.system_state_raw)
        except ValueError:
            return None

    @property
    def error(self) -> ResponseCode | None:
        try:
            return ResponseCode(self.error_raw)
        except ValueError:
            return None

    @property
    def is_ack(self) -> bool:
        return self.error_raw == int(ResponseCode.CENTRAL_RESPONDE)

    @classmethod
    def parse(cls, raw: bytes) -> ResponseFrame:
        if len(raw) < RESPONSE_FRAME_MIN_SIZE:
            raise ValueError(
                f"Frame de resposta precisa de >= {RESPONSE_FRAME_MIN_SIZE} bytes, "
                f"recebido {len(raw)}"
            )
        if raw[0] != SOF:
            raise ValueError(f"SOF inválido: esperado 0x{SOF:02X}, recebido 0x{raw[0]:02X}")

        return cls(
            addr=(raw[1] << 8) | raw[2],
            cmd=raw[3],
            payload=bytes(raw[4:8]),
            status_corrente=raw[8],
            status_geral=StatusGeral(raw[9] & 0x3F),  # mascara bits de stack 6-7
            status_geral1=StatusGeral1(raw[10]),
            sw_version=raw[11],
            system_state_raw=raw[12],
            error_raw=raw[13],
            raw=bytes(raw[:RESPONSE_FRAME_SIZE]),
        )


# =============================================================================
# HELPERS DE ALTO NÍVEL
# =============================================================================


def is_grupo_sismica(state: int | SystemState) -> bool:
    """True se o estado pertence ao grupo sísmica (0xBx)."""
    return (int(state) & GRUPO_SISMICA_MASK) == GRUPO_SISMICA_VALUE


def addr_split(addr: int) -> tuple[int, int]:
    """Divide um endereço de 16 bits em (ADDH, ADDL)."""
    return (addr >> 8) & 0xFF, addr & 0xFF


def addr_join(addh: int, addl: int) -> int:
    """Junta ADDH/ADDL em endereço de 16 bits."""
    return ((addh & 0xFF) << 8) | (addl & 0xFF)


# =============================================================================
# SMOKE TESTS — executar com `python delfos_protocol.py`
# =============================================================================


def _smoke_tests() -> None:
    # CRC: valor verificado por execução manual do algoritmo do firmware.
    # crc16_ccitt(b"123456789") == 0x29B1 é o teste vector clássico CCITT-FALSE.
    assert crc16_ccitt(b"123456789") == 0x29B1, hex(crc16_ccitt(b"123456789"))
    assert crc16_ccitt(b"") == 0xFFFF

    # Build de comando UASG curto (7 bytes — SOF + ADDH + ADDL + CMD + P1 + P2 + P3).
    f = build_command_frame(addr=0x0001, cmd=Command.ENVIA_ENDERECO)
    assert f == bytes([0x7F, 0x00, 0x01, 0x41, 0x00, 0x00, 0x00]), f.hex()

    # Build com validação de parâmetro.
    f = build_command_frame(
        addr=BROADCAST_ADDR,
        cmd=Command.SET_CYCLE_PERIOD,
        p1=CyclePeriod.CYCLE_8S_PULSE_2S,
    )
    assert f == bytes([0x7F, 0xFF, 0xFD, 0x42, 0x31, 0x00, 0x00]), f.hex()

    # Validação rejeita parâmetro inválido.
    try:
        build_command_frame(addr=0, cmd=Command.SET_CYCLE_PERIOD, p1=0x33)
    except ValueError as exc:
        assert "0x33" in str(exc) and "SET_CYCLE_PERIOD" in str(exc)
    else:
        raise AssertionError("Esperado ValueError para p1=0x33 em SET_CYCLE_PERIOD")

    # Build de comando MR64 (frame longo).
    f = build_command_frame(
        addr=0x0010,
        cmd=Command.CONEX_ELETRODO,
        p1=0x55,
        p2=0x00,
        p3=0x01,
        extras=bytes(11),
    )
    assert len(f) == COMMAND_FRAME_SIZE_MR64, len(f)
    assert f[3] == 0x52 and f[4] == 0x55

    # Parse de resposta — ACK simulado.
    raw = bytes(
        [
            SOF,  # 0
            0x00,
            0x01,  # 1-2 addr
            Command.PING_CENTRAL,  # 3 cmd
            0x00,
            0x00,
            0x00,
            0x00,  # 4-7 payload
            0x00,  # 8  StatusCorrente
            StatusGeral.CORRENTE_IP_ON,  # 9 StatusGeral
            0x00,  # 10 StatusGeral1
            0x14,  # 11 sw_version
            SystemState.IDLE,  # 12
            ResponseCode.CENTRAL_RESPONDE,  # 13
            0x00,
            0x00,  # 14-15 pad
        ]
    )
    resp = ResponseFrame.parse(raw)
    assert resp.addr == 0x0001
    assert resp.cmd_enum == Command.PING_CENTRAL
    assert resp.is_ack
    assert resp.system_state == SystemState.IDLE
    assert StatusGeral.CORRENTE_IP_ON in resp.status_geral
    assert resp.error == ResponseCode.CENTRAL_RESPONDE

    # is_grupo_sismica.
    assert is_grupo_sismica(SystemState.MEDINDO_MASW_13)
    assert is_grupo_sismica(0xB7)
    assert not is_grupo_sismica(SystemState.IDLE)

    # addr_split / addr_join roundtrip.
    assert addr_split(0xABCD) == (0xAB, 0xCD)
    assert addr_join(0xAB, 0xCD) == 0xABCD

    print("OK — smoke tests passaram")


if __name__ == "__main__":
    _smoke_tests()
