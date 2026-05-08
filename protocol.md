# Protocolo Console ↔ Central Delfos

Documentação dos comandos aceitos pela DelfosCentralFT extraída diretamente do
firmware (não do header `DefinicoesGeraisDelfos.h`, que está desatualizado).

**Fontes**:
- `DelfosCentralFT/ProtocoloTxCentral.c` — switch principal de comandos
- `DelfosCentralFT/MontaFrameTxCentral.c` — parser do frame Console → Central
- `DelfosCentralFT/CtrlFonteCor_Ciclo.c` — layout do frame Central → Console
- `DelfosCentralFT/DelfosCentralFunctions.c` — algoritmo de CRC

Implementação Python: [`delfos/protocol.py`](delfos/protocol.py).

---

## Sumário

- [Frame format](#frame-format)
- [Endereços especiais](#endereços-especiais)
- [Comandos aceitos pela Central](#comandos-aceitos-pela-central)
- [Detalhamento por comando](#detalhamento-por-comando)
- [Códigos de resposta](#códigos-de-resposta)
- [Estados do sistema](#estados-do-sistema)
- [Status flags](#status-flags)
- [Comandos legados / desativados](#comandos-legados--desativados)
- [Inconsistências do header original](#inconsistências-do-header-original)

---

## Frame format

### Console → Central (request)

Sem CRC. Dois tamanhos:

**Frame UASG (7 bytes)** — todos os comandos exceto MR64:

| Byte | Valor | Significado                       |
|-----:|-------|-----------------------------------|
|    0 | `7F`  | SOF (Start of Frame)              |
|    1 | ADDH  | Endereço da unidade (high byte)   |
|    2 | ADDL  | Endereço da unidade (low byte)    |
|    3 | CMD   | Opcode do comando                 |
|    4 | P1    | Parâmetro 1                       |
|    5 | P2    | Parâmetro 2                       |
|    6 | P3    | Parâmetro 3                       |

> Validado em `MontaFrameTxCentral.c`: a state machine sempre lê P3 (estado 17)
> antes de fechar o frame UASG, mesmo quando comandos não usam P3 — nesses
> casos enviar `0x00`.

**Frame MR64 (18 bytes)** — apenas para `CONEX_ELETRODO` (`0x52`) com P1 ≥ `0x55`:

| Byte | Valor   | Significado                                    |
|-----:|---------|------------------------------------------------|
|    0 | `7F`    | SOF                                            |
|    1 | ADDH    | Endereço                                       |
|    2 | ADDL    | Endereço                                       |
|    3 | `52`    | Opcode CONEX_ELETRODO                          |
|    4 | ≥`55`   | Sub-comando MR64 (`AA`=conecta, `55`=limpa)    |
|    5 | I+      | Eletrodo de corrente positivo `{0..31, FF}`    |
|    6 | I-      | Eletrodo de corrente negativo `{0..31, FF}`    |
| 7-15 | S0..S8  | Relé de sinal nas placas 0..8 `{0..31, FF}`    |
|   16 | linha   | Seleciona linha (0..7)                         |
|   17 | vago    |                                                |

### Central → Console (response, 16 bytes)

Sem CRC. Layout:

| Byte  | Resposta a comando             | InfCorrenteTransm autônomo            |
|------:|--------------------------------|---------------------------------------|
|     0 | `7F` SOF                       | `7F` SOF                              |
|   1-2 | ADDH, ADDL (eco)               | `00 00`                               |
|     3 | CMD (eco)                      | `53` (InfCorrenteTransm)              |
|   4-7 | Eco de P1, P2 + erro + state   | Corrente IP instantânea (4 bytes)     |
|     8 | `StatusCorrente`               | Corrente IP média byte 0              |
|     9 | `StatusGeral`                  | Corrente IP média byte 1              |
|    10 | `StatusGeral1`                 | Corrente IP média byte 2              |
|    11 | `sw_version`                   | Corrente IP média byte 3              |
|    12 | `SystemState`                  | `SobretensaoFonteCorrente`            |
|    13 | `ResponseCode` / argmto        | argmto                                |
| 14-15 | pad                            | pad                                   |

### CRC16 (apenas no enlace RS485, NÃO no console)

Algoritmo CCITT-FALSE: poly `0x1021`, init `0xFFFF`, MSB first, sem reflect, sem XOR final.
Disponível em Python como `crc16_ccitt(data)` para sniff de RS485.

---

## Endereços especiais

| Endereço | Significado                         |
|----------|-------------------------------------|
| `0x0000` | Ping na Central (se cmd=`ENVIA_ENDERECO`) |
| `0xFFFD` | Broadcast (`ADDH=0xFF, ADDL=0xFD`)  |

---

## Comandos aceitos pela Central

Todos os opcodes abaixo têm `case` ativo em `ProtocoloTxCentral.c:203`. Qualquer
outro opcode retorna `ResponseCode.COMANDO_INDEFINIDO` (`0x36`).

| Opcode | ASCII | Nome                        | P1                      | P2                | P3                | Estado req.        |
|-------:|:-----:|-----------------------------|-------------------------|-------------------|-------------------|--------------------|
| `0x41` | "A"   | `ENVIA_ENDERECO`            | —                       | —                 | —                 | IDLE / IDLE_SISMICA|
| `0x42` | "B"   | `SET_CYCLE_PERIOD`          | `CyclePeriod`           | —                 | —                 | IDLE               |
| `0x43` | "C"   | `RESIST_CONTATO`            | (forçado a `0x31`)      | (forçado `0x31`)  | —                 | IDLE               |
| `0x44` | "D"   | `ENVIA_RES_CONTATO`         | —                       | —                 | —                 | qualquer           |
| `0x45` | "E"   | `INICIA_MEDE_GEOFISICA`     | `GeoVariable` (0x30-33) | size buffer       | fração buffer     | depende de P1      |
| `0x46` | "F"   | `PARA_MEDE_GEOFISICA`       | `GeoVariable`           | —                 | —                 | qualquer           |
| `0x47` | "G"   | `ENVIA_VARIAVEIS_GEO`       | `GeoVariable` + `0x35`  | —                 | —                 | IDLE / UPLOADING   |
| `0x4A` | "J"   | `REGISTRA_SISMICA`          | `SismicState`           | threshold mult.   | `SeismicSampleRate` (124-127) | grupo SISMICA |
| `0x4B` | "K"   | `LIGA_ALIM_UASGS`           | —                       | —                 | —                 | qualquer           |
| `0x36` | "6"   | `MEDE_RES_CONTATO_TURBO` ⚠️ | —                       | PWM (≤34)         | —                 | qualquer           |
| `0x51` | "Q"   | `DEFINE_REPETIDOR`          | `0x30..0x38`            | —                 | —                 | IDLE               |
| `0x52` | "R"   | `CONEX_ELETRODO`            | `ElectrodeMode` ou ≥`0x55` (MR64) | `ElectrodeMode` | `ElectrodeE3Mode` | qualquer |
| `0x53` | "S"   | `INF_CORRENTE_TRANSM`       | —                       | —                 | —                 | qualquer (e autônomo) |
| `0x55` | "U"   | `CDO_TRANSMISSOR_CORRENTE`  | `CurrentControlMode`    | PWM/corrente      | tipo ciclo / stack| depende de P1      |
| `0x57` | "W"   | `PING_CENTRAL`              | mult. timeout (`0xFF` = default) | —          | —                 | qualquer           |
| `0x59` | "Y"   | `DESLIGA_ALIM_UASGS`        | —                       | —                 | —                 | qualquer           |

⚠️ `MEDE_RES_CONTATO_TURBO` (`0x36`) **não tem `#define`** no header — comando novo
detectado lendo `ProtocoloTxCentral.c:968`.

---

## Detalhamento por comando

### `0x41` ENVIA_ENDERECO ("A")

Solicita endereço da unidade alvo.

- **Caso especial**: ADDH=`0` e ADDL=`0` vira ping na Central (responde imediatamente
  com `CentralResponde`), não consulta UASG.
- **Caso normal**: liga alimentação das UASGs e encaminha pedido para a remota
  endereçada. A remota responde com seu próprio endereço.
- **Estado requerido**: `IDLE` ou (`IDLE_SISMICA` com `EstadoSismica2 == IDLE`).
- **Resposta**: `CentralResponde` (ACK) ou `ForaEstadoPermitido` se em estado errado.

### `0x42` SET_CYCLE_PERIOD ("B")

Define o multiplicador do PLL → frequência do ciclo IP.

- **P1**: ASCII de `'1'` a `'9'`, exceto `'3'`. Ver `CyclePeriod`:

| P1     | Período / Pulso        | Multiplicador `IncPLLIp` |
|:------:|------------------------|--------------------------|
| `0x31` | 8 s / 2 s              | × 1                      |
| `0x32` | 4 s / 1 s              | × 2                      |
| `0x34` | 2 s / 0.5 s            | × 4                      |
| `0x36` | 1.33 s / 0.33 s        | × 6                      |
| `0x37` | 1.33 s / 0.33 s (alt)  | × 6 (idêntico ao 0x36)   |
| `0x38` | 1 s / 0.25 s           | × 8                      |
| `0x39` | 0.5 s / 0.125 s        | × 16                     |

- **Estado requerido**: `IDLE`. Caso contrário → `ForaEstadoPermitido`.
- **P1 fora da tabela** → `OutOfRange`.

### `0x43` RESIST_CONTATO ("C")

Inicia medida de resistência de contato.

- P1 e P2 são forçados a `0x31` no firmware (qualquer valor passado é sobrescrito).
- Em broadcast, não há resposta direta da remota.
- **Estado requerido**: `IDLE`.
- **Side effect**: limpa todos os bits de `StatusGeral` exceto seta `MED_RES_ON`.

### `0x44` ENVIA_RES_CONTATO ("D")

Solicita o valor da resistência medida. Resposta é payload short.

### `0x45` INICIA_MEDE_GEOFISICA ("E")

Inicia aquisição da variável geofísica selecionada. **Broadcast — não tem resposta**.

| P1     | Variável         | Estado requerido       |
|:------:|------------------|------------------------|
| `0x30` | IP / VP          | `TRIP_ON` ou `MEDINDO_IP` |
| `0x31` | VP               | `TRIP_ON` ou `MEDINDO_IP` |
| `0x32` | SP               | `IDLE`                 |
| `0x33` | Sísmica geofones 1 e 3 | qualquer (configura PLL) |

- **P1 = 0x33 (sísmica)**:
  - `IndSizeBufferSis = P2 & 0x3C` (valores `{4, 8, 16, 32}`)
  - `BufferFraction   = P3 & 0x0F`
  - `TempoRegSismica = (IndSizeBufferSis * 49) - (BufferFraction * 49)`
  - Força ciclo PLL para 8s/2s e troca timer para `Timer0PeriodoSismPas`.
- **Bit de StatusGeral** vai para `MED_GEO_ON`/`MED_IP_ON`. Bits 6-7 recebem
  `(P1 << 6) & 0xC0` (rejeição de stack — não usado em Delfos).

### `0x46` PARA_MEDE_GEOFISICA ("F")

Encerra registro e força `SystemState = IDLE`. Broadcast — sem resposta de remota,
mas a Central responde `CentralResponde`. Reinicializa ADC0/ADC1.

### `0x47` ENVIA_VARIAVEIS_GEO ("G")

Solicita upload das amostras adquiridas.

| P1     | Variável                        | Payload Resp.            | Timeout    |
|:------:|---------------------------------|--------------------------|------------|
| `0x30` | IP / VP                         | `UASGTxPayloadLong` (201)| `TimeoutUR_IP` |
| `0x31` | VP                              | `UASGTxPayloadVPSP` (28) | `TimeoutUR_SP_VP` |
| `0x32` | SP                              | `UASGTxPayloadVPSP` (28) | `TimeoutUR_SP_VP` |
| `0x33` | Sísmica geofones 1 e 3          | `UASGTxPayloadSismica` (~6400) | `TimeoutUR_Sismica` |
| `0x35` | Fullwave                        | `UASGTxPayloadFullWave` | `TimeoutUR_FW` |

- **P1 = 0x34** (segundo conjunto de geofones) está comentado no firmware.
- Estado requerido: `IDLE`, `UPLOADING`, ou `EstadoSismica1 == IDLE`.

### `0x4A` REGISTRA_SISMICA ("J")

Controla o registro sísmico. **Estado requerido: grupo SISMICA**
(`SystemState & 0xF0 == 0xB0`).

| P1     | Estado          | Comportamento                                                          |
|:------:|-----------------|------------------------------------------------------------------------|
| `0x30` | CONTINUO        | Inicia registro circular contínuo no buffer                            |
| `0x31` | POS             | Registra um buffer e para. Time-stamp = `PLLIpW` no instante           |
| `0x32` | MEIO            | Registra meio buffer e para                                            |
| `0x33` | MEIO_PSEUDO_ATIVO | Registra ao detectar evento sísmico (geofone sentinela). Requer estar em CONTINUO antes |
| `0x34` | IDLE            | Para o registro                                                        |
| `0x35` | SENDING         | Envia o buffer registrado (responde com payload sísmica grande)        |
| `0x37` | SAI_MEDE_SISMICA | Sai completamente do modo sísmica e restaura período do ciclo         |

- **P2 (apenas em P1 = `0x33`)**: multiplicador do threshold (`SismicaThreshold`).
  - `P2 = 0` → threshold = `Vi1mv / 4`
  - `P2 ≠ 0` → threshold = `P2 * Vi1mv` (1mV scaled to Q28)
- **P3**: `SR_Const` (sample rate constant). Aceita `{124, 125, 126, 127}`. Default `125` se outro valor.

### `0x4B` LIGA_ALIM_UASGS ("K")

Liga a alimentação das UASGs Delfos. Resposta `CentralResponde` via `ComandoPingCentral`.

> ⚠️ No header `DefinicoesGeraisDelfos.h` o opcode `0x4B` está duplicado como
> `SendBurst` e `LigaAlimUASGs`. Na Central é `LigaAlimUASGs` que ganha.

### `0x36` MEDE_RES_CONTATO_TURBO ("6") — comando novo, sem #define no header

Mede resistência de contato pelo transmissor da Central em modo UASGi. Similar ao
`CDO_TRANSMISSOR_CORRENTE` com `P1=MEDE_RESISTENCIA`, mas sem turbo.

- **P2**: programação do PWM (potência) — **deve ser ≤ 34 (`MaxPot`)** ou retorna `OutOfRange`.
- Define `RM1RM64 = 0xA2` (modo UASGi com pulsos pos/neg).

### `0x51` DEFINE_REPETIDOR ("Q")

Define a ordem de repetição da unidade endereçada.

- **P1**: ASCII de `'0'` a `'8'` (0x30..0x38) — fora desta faixa retorna `OutOfRange`.
- **Estado requerido**: `IDLE`.
- Comando pode ser broadcast.

### `0x52` CONEX_ELETRODO ("R")

Conecta eletrodos de corrente. Tem dois modos baseados em P1:

#### Modo Delfos UASG (P1 < `0x55`)

Frame curto de 6 bytes.

| P1 / P2 | ElectrodeMode  | Significado                                                          |
|:-------:|----------------|----------------------------------------------------------------------|
| `0x30`  | DESCONECTA     | Mede sinal — relé e FET desligados                                   |
| `0x31`  | CORRENTE_A     | Corrente positiva no 1º quarto do ciclo, negativa no 3º              |
| `0x32`  | CORRENTE_B     | Corrente negativa no 1º quarto do ciclo, positiva no 3º              |

| P3      | ElectrodeE3Mode | Significado                                                  |
|:-------:|-----------------|--------------------------------------------------------------|
| `0x30`  | NORMAL          | Operação normal                                              |
| `0x33`  | DESCONECTA      | Relé liga, desconecta entrada do ADC do eletrodo             |

- **Em broadcast**, só aceita P1=P2=P3=`0x30` (limpa tudo). Caso contrário
  → `NPemitdoBroadcast` (`0x61`).

#### Modo MR64 (P1 ≥ `0x55`)

Frame longo de 18 bytes — ver tabela na seção [Frame format](#frame-format).
Só permitido se `StatusCorrente == PWM_idle` (transmissor desligado), caso contrário
retorna `CorrenteLigada` (`0x33`).

- O byte 16 (selecLinha) deve ser ≤ 7 ou retorna `OutOfRange`.

### `0x53` INF_CORRENTE_TRANSM ("S")

Solicita corrente do shunt. **Também é emitido autonomamente** pela Central a
cada ciclo IP on (ver `CtrlFonteCor_Ciclo.c:531+`).

- Se `CorrentePronta == 1`: chama `EnviaCorrenteTRxtoServer()`.
- Senão: chama `EnviaCorrenteTRxtoServerErro()` (corrente precisa estar ligada).

Resposta tem layout especial: bytes 4-7 = corrente IP instantânea (4 bytes long),
bytes 8-11 = corrente IP média.

### `0x55` CDO_TRANSMISSOR_CORRENTE ("U")

Controla o transmissor de corrente local da Central.

| P1     | CurrentControlMode      | Comportamento                                                  |
|:------:|-------------------------|----------------------------------------------------------------|
| `0x30` | DESLIGA                 | `ParaTransmissorCorrente()`                                    |
| `0x31` | MEDE_RESISTENCIA        | Liga para medir resistência. P2 = PWM (≤ 34). Modo UASGi.      |
| `0x32` | ABORTA                  | Emergência — corta PWM. Reseta state para IDLE.                |
| `0x33` | LIGA_AUTO_AJUSTE        | Modo controle de corrente. P2 = corrente em décimas (1..100).  |
| `0x34` | INICIA_SEQUENCIAMENTO   | Inicia ciclo. P2 = PWM (≤ 34). P3 = `CurrentCycleType`.        |
| `0x35` | MUDA_CORRENTE_ON_THE_FLY| P2 = PWM novo. Requer `StatusCorrente == EnviaCicloCorrente`.  |
| `0x37` | LIGA_TURBO              | Modo turbo (sem tempo off). P2 = corrente. P3 = stack count.   |

**P3 (CurrentCycleType) quando P1 = `0x34`**:

| P3 | Tipo                           | RM1RM64 |
|:--:|--------------------------------|:-------:|
| 0  | UASG (só pulsos positivos)     | `0xA0`  |
| 1  | UASGi (pos e neg)              | `0xA1`  |
| 2  | UASGi sem tempo off            | `0xA2`  |

- P2 fora do range → `OutOfRange`.
- P1 desconhecido → `ParametroIndefinido`.
- `MUDA_CORRENTE_ON_THE_FLY` com corrente desligada → `CorrenteDesligada`.

### `0x57` PING_CENTRAL ("W")

Ping na Central, retorna `CorrenteAlimUASGs` no payload (4 bytes nas posições 4-7).

- **P1**: multiplicador do timeout de comunicação.
  - `P1 = 0xFF` → mantém default (multiplicador interno = `0xFE`).
  - Outro valor → `MultiplicadorReset = P1`, `TempoUltimaComPC = TempoEsperaCommPC * (P1 + 1)`.

> ⚠️ Conflito: o header tem `Wakeup = 0x57` e `PingCentralDelfos = 0x57`. Na Central
> é `PingCentralDelfos` que ganha.

### `0x59` DESLIGA_ALIM_UASGS ("Y")

Desliga a alimentação das UASGs Delfos. Resposta `CentralResponde`.

> ⚠️ Conflito: o header tem `GoSleep = 0x59` e `DesligaAlimUASGs = 0x59`. Na Central
> é `DesligaAlimUASGs` que ganha.

---

## Códigos de resposta

Byte 13 do frame Central → Console.

| Código | Nome                       | Significado                                       |
|-------:|----------------------------|---------------------------------------------------|
| `0x30` | `INDEFINIDO`               | Resposta padrão sem sinal                         |
| `0x31` | `MEDIDA_EM_ANDAMENTO`      | Já existe medida ativa                            |
| `0x32` | `FORA_ESTADO_PERMITIDO`    | Comando incompatível com o `SystemState` atual    |
| `0x33` | `CORRENTE_LIGADA`          | Comando só permitido com corrente off             |
| `0x34` | `CORRENTE_DESLIGADA`       | Comando só permitido com corrente on              |
| `0x36` | `COMANDO_INDEFINIDO`       | Opcode desconhecido na Central                    |
| `0x37` | `PARAMETRO_INDEFINIDO`     | Sub-parâmetro inválido                            |
| `0x38` | `OUT_OF_RANGE`             | Parâmetro fora do range aceito                    |
| `0x39` | `CAPT_SISMICA_ON`          | Captura sísmica ativa, comando bloqueado          |
| `0x40` | `INICIANDO_CENTRAL`        | Enviado após reset da Central                     |
| `0x61` | `NP_PERMITIDO_BROADCAST`   | Parâmetro inválido em broadcast                   |
| `0x62` | `CENTRAL_RESPONDE`         | **ACK — comando aceito**                          |
| `0x63` | `CORRENTE_CONVERGINDO`     | Esperando convergir medida de corrente            |
| `0x64` | `ELETRODO_COR_ABERTO`      | Eletrodo de corrente aberto                       |
| `0x65` | `PONTE_H_LADO_ABERTO`      | Desbalanço entre ciclos da corrente               |

---

## Estados do sistema

Byte 12 do frame de resposta. Define o que a Central está fazendo.

| Hex    | Estado                       | Descrição                                       |
|-------:|------------------------------|-------------------------------------------------|
| `0x00` | `IDLE`                       | Sistema parado                                  |
| `0x01` | `TRIP_ON`                    | Transmissor IP on, sincronizando ciclo          |
| `0x02` | `MEDINDO_IP`                 | Em medição de IP                                |
| `0x03` | `PRE_MEDINDO_IP`             | Indicação para ir para medição                  |
| `0x04` | `MED_RES_CONT_0`             | Mede resistência dipolo 0                       |
| `0x05` | `MED_RES_CONT_1`             | Mede resistência dipolo 1                       |
| `0x06` | `DESLIGANDO_MEDE_IP`         | Após medir IP, espera comando para resistência  |
| `0x07` | `MED_RES_CONTATO`            | Remota mede resistência                         |
| `0x08` | `UPLOADING`                  | Subindo variáveis adquiridas                    |
| `0x09` | `FINAL_UPLOADING`            | Final do upload                                 |
| `0x0B` | `ETERNAL_BURST`              | Transmite bursts sem parar                      |
| `0x0C` | `SAI_ETERNAL_BURST`          | Sai do burst eterno                             |
| `0x20` | `ID_MATRIX`                  | Identificando posição em campo                  |
| `0x80` | `ZERA_OFFSET_ADC`            | Calibração de offset                            |
| `0x81` | `ANALISE_ADC`                | Análise do ADC                                  |
| `0x82` | `POTENCIAL_ELETRODO`         | Análise do potencial do eletrodo                |
| `0xA0` | `MEDINDO_SP`                 | Medindo potencial espontâneo                    |
| `0xB0` | `IDLE_SISMICA`               | Modo sísmica idle (grupo `0xB?`)                |
| `0xB1` | `MEDINDO_MASW_13`            | MASW geofones 1 e 3                             |
| `0xB2` | `MEDINDO_MASW_24`            | MASW geofones 2 e 4                             |
| `0xB3` | `MEDINDO_SISMICA_PASSIVA`    | Sísmica passiva                                 |
| `0xD0` | `UPLOADING_VAR_GEO`          | Subindo variáveis geofísicas via RS485          |
| `0xDF` | `DEBUGING_ADC`               | Debug do ADC                                    |

**Grupo SISMICA**: qualquer estado com `(state & 0xF0) == 0xB0`. Use
`is_grupo_sismica(state)` na lib Python.

---

## Status flags

### `StatusGeral` (byte 9)

| Bit | Hex   | Flag                  | Significado                                  |
|----:|-------|-----------------------|----------------------------------------------|
|   0 | `0x01`| `CORRENTE_IP_ON`      | Corrente IP on                               |
|   1 | `0x02`| `MED_GEO_ON` / `MED_IP_ON` | Medição geofísica em andamento          |
|   2 | `0x04`| `MED_RES_ON`          | Medindo resistência                          |
|   3 | `0x08`| `TOPOLOGIA_ON`        | Montando topologia da rede                   |
|   4 | `0x10`| `ID_MATRIX_ON`        | Identificando posição das unidades           |
|   5 | `0x20`| `WAKING_UP_ON`        | Acordando unidades remotas                   |
| 6-7 | -     | (rejeição de stack — não usado em Delfos) |                          |

### `StatusGeral1` (byte 10)

| Bit | Hex   | Flag                       | Significado                                |
|----:|-------|----------------------------|--------------------------------------------|
|   0 | `0x01`| `VP`                       | Medição de VP                              |
|   1 | `0x02`| `SP`                       | Medição de SP                              |
|   2 | `0x04`| `SISM_SET_0`               | MASW conjunto de geofones 0                |
|   3 | `0x08`| `MODO_SISMICA_0`           |                                            |
|   4 | `0x10`| `MODO_SISMICA_1`           |                                            |
|   5 | `0x20`| `REG_SISMICA`              | Registrando amostras de sísmica            |
|   6 | `0x40`| `REG_SISM_PSEUDO_ATV`      | Capturando sísmica (gatilho disparado)     |
|   7 | `0x80`| `SISM_PSEUDO_ENGATILHADA`  | Geofone sentinela armado                   |

---

## Comandos legados / desativados

A UASG (`Delfos_UASG/ExecutaComandoDelfos.c`) ainda implementa estes comandos,
mas a Central tem o trecho dentro de `/* ... */` em `ProtocoloTxCentral.c:672-726`.
Logo, do console retornam `COMANDO_INDEFINIDO`.

| Opcode | ASCII | Nome                  | Uso original                                          |
|-------:|:-----:|-----------------------|-------------------------------------------------------|
| `0x48` | "H"   | `SENTIU_CORRENTE`     | Broadcast com resposta de quem sentiu corrente vizinha |
| `0x49` | "I"   | `CORRENTE_MATRIX_ID`  | Aplica corrente para identificação da matriz          |
| `0x4D` | "M"   | `MATRIX_ID`           | Entra em modo identificação da matriz                 |

Disponíveis em Python como `LegacyCommand.SENTIU_CORRENTE`, etc., para se um dia
forem reativados.

---

## Inconsistências do header original

Anomalias detectadas em `CommonFilesDelfos/DefinicoesGeraisDelfos.h` durante a
extração:

### Opcodes duplicados (mesmo valor, dois nomes)

| Opcode | Nome A         | Nome B               | Quem ganha na Central |
|-------:|----------------|----------------------|-----------------------|
| `0x4B` | `SendBurst`    | `LigaAlimUASGs`      | `LigaAlimUASGs`       |
| `0x57` | `Wakeup`       | `PingCentralDelfos`  | `PingCentralDelfos`   |
| `0x59` | `GoSleep`      | `DesligaAlimUASGs`   | `DesligaAlimUASGs`    |

### Opcodes no header sem `case` na Central

- `0x50` `EnviaCorrenteComut` — comentado em `ProtocoloTxCentral.c:764`
- `0x54` `SendCicloIP` — sem case
- `0x56` `DeepWakeup` — sem case
- `0x5A` `GoDeepSleep` — sem case
- `0x4B` `SendBurst` (já coberto pelo conflito acima)
- `0x57` `Wakeup` (idem)
- `0x59` `GoSleep` (idem)

### Comandos no firmware sem `#define` no header

- `0x36` "6" — `MEDE_RES_CONTATO_TURBO` (descoberto em `ProtocoloTxCentral.c:968`)

### Valores de parâmetro que mudaram em relação à doc no header

- `SET_CYCLE_PERIOD` no header (linhas 7-13) lista multiplicadores `0..6`. O
  firmware aceita `'1'..'9'` (`0x31..0x39`, exceto `0x33`) — formato ASCII.
- `INICIA_MEDE_GEOFISICA` no header (linhas 15-34) descreve um Parâmetro 0
  para "rejeição de filtro" e um Parâmetro 1 para "variável". No firmware
  da Central, P1 leva a "variável" e os bits `<<6` viram filtro de stack.
  O parâmetro de "rejeição" é o byte que o console manda em P1.
- `RegistraSismica` no header lista `SismicContinuo..SendingSis` (`0x30..0x35`).
  O firmware aceita também `0x37` (sair do modo sísmica), que **não está no header**.
