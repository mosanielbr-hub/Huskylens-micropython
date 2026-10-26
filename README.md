# HuskyLens MicroPython — HuskyLens 1 (v1.0.0-rc1)

Biblioteca independente em **um único arquivo `huskylens.py`**, destinada à **HuskyLens original (HuskyLens 1)** em placas com MicroPython e interfaces UART ou I²C. **Não se destina à HuskyLens 2.** Implementa comandos descritos no protocolo oficial 0.5.1 e uma opção experimental de handshake presente no Arduino oficial.

Este repositório contém **somente a biblioteca e seus exemplos, testes e documentação**. Não depende de um robô, de motores nem de um projeto específico.

**Status de validação:** testes simulados em CPython passaram; comunicação em hardware real **não testada**. Alguns comandos dependem da versão de firmware e do cartão microSD. Não prometemos suporte a configurações sem comando no protocolo público.

## Instalação

1. Copie `huskylens.py` para `/lib/` (ou para a raiz) do dispositivo MicroPython, usando sua ferramenta de transferência preferida.
2. Configure a HuskyLens para o mesmo protocolo: `Serial/UART` ou `I2C`, pelo menu da própria câmera.
3. Execute o teste da pasta `examples/` (copie apenas se precisar).

### UART (exemplo com ESP32)

HuskyLens TX → ESP32 GPIO16 (RX2); HuskyLens RX → ESP32 GPIO17 (TX2); GND comum; alimentação conforme as especificações do seu módulo. **Confira os níveis elétricos dos sinais antes de ligar ao ESP32 (GPIO não tolera 5 V).** A câmera deve estar configurada no modo UART 9600 8N1.

```python
from huskylens import HuskyLens
camera = HuskyLens(tx=17, rx=16, uart_id=2)
print('Conectada?', camera.ping())
```

### I²C

Endereço I²C da HuskyLens = `0x32` (diferente do byte `0x11` presente nos pacotes do protocolo). O exemplo usa 100 kHz. O barramento pode ser compartilhado com outros periféricos I²C, desde que os endereços não conflitem e as especificações elétricas sejam respeitadas.

```python
from huskylens import HuskyLens
camera = HuskyLens(interface='i2c', sda=21, scl=22)
print(camera.ping())
# Ou passar um objeto existente de machine.I2C:
# camera = HuskyLens(i2c=i2c)
```

## API (todos os 7 modos)

```python
camera.set_algorithm('FACE_RECOGNITION')
camera.set_algorithm('OBJECT_TRACKING')
camera.set_algorithm('OBJECT_RECOGNITION')
camera.set_algorithm('LINE_TRACKING')
camera.set_algorithm('COLOR_RECOGNITION')
camera.set_algorithm('TAG_RECOGNITION')
camera.set_algorithm('OBJECT_CLASSIFICATION')
# Também aceita inteiros de 0 a 6, e nomes com prefixo ALGORITHM_.
```

## Detecções

```python
camera.request()                         # Tudo: blocks e arrows, na ordem recebida
camera.request('blocks')
camera.request('arrows')
camera.request('learned')                # Apenas objetos aprendidos
camera.request('learned_blocks')
camera.request('learned_arrows')
camera.request('all', object_id=1)        # Filtra por ID
camera.get_blocks(object_id=1)          # Lista de Block
camera.get_arrows(object_id=1)          # Lista de Arrow
camera.get_learned()
camera.get_learned_blocks()
camera.get_learned_arrows()

print(camera.frame, camera.learned_count)
print(camera.count(), camera.count_blocks(), camera.count_arrows())
print(camera.is_learned(1), camera.has_id(1))
```

- `Block`: `.x`, `.y` (centro de 320×240), `.width`, `.height`, `.id`; aliases `.x_center`, `.y_center`.
- `Arrow`: `.x_origin`, `.y_origin`, `.x_target`, `.y_target`, `.id`.
- `camera.results`, `camera.blocks`, `camera.arrows`: resultados **da última leitura bem-sucedida**. Limpos ao início de cada nova consulta.
- `ID == 0`: detecção ainda não aprendida.

## Aprendizagem, interface e microSD

| Método | Efeito | Comando |
|---|---|---|
| `ping()` | Verifica comunicação | `0x2C` |
| `learn(1)` | Aprende objeto atual como ID 1 | `0x36` |
| `forget()` | Esquece aprendizado do algoritmo atual | `0x37` |
| `set_custom_name(1, 'BOLA')` | Dá nome a ID conhecido | `0x2F` |
| `custom_text('MICROPYTHON', 100, 30)` | Sobrepõe texto na tela da HuskyLens | `0x34` |
| `clear_text()` | Remove textos da tela | `0x35` |
| `save_photo()` | Salva **foto na SD da câmera** | `0x30` |
| `save_screenshot()` | Salva **captura da interface na SD** | `0x39` |
| `save_model(1)` | Salva aprendizado do algoritmo atual na SD | `0x32` |
| `load_model(1)` | Carrega aprendizado do algoritmo atual da SD | `0x33` |
| `is_pro()` | Consulta modelo Pro (firmware-dependente) | `0x3B` |
| `firmware_handshake('0.4.1')` | **Experimental**: verifica resposta ao *valor esperado*; não consulta a versão instalada | `0x3C` |
| `raw_command(cmd, payload)` | Baixo nível: retorna `(comando_resposta, bytes)` | configurável |

**Nomes e textos:** entre 1 e 20 caracteres ASCII (evite acentos); ID para nomes de 1 a 255; texto x=0..319, y=0..239. Até 10 textos simultâneos conforme o protocolo. Os comandos microSD requerem cartão acessível na câmera e firmware que os implemente. O retorno `OK` confirma resposta ao comando, **não** que você já leu ou recebeu o arquivo no ESP32.

**Detalhe de compatibilidade:** a documentação do protocolo usa strings de comprimento variável e `x%255` para textos; a biblioteca Arduino tem pequenas diferenças nesses encodes. Esta versão segue o **documento do protocolo**. Alguns firmwares podem exigir ajustes para funções de texto; teste no aparelho antes de depender delas.

## Robustez

- Validação de checksum e ressincronização após pacotes corrompidos.
- Respostas UART fragmentadas e transações I²C em blocos de 16 bytes.
- Timeout por pacote, limitação de resultados (64 por padrão), descarte de resultados parciais.
- Reenvio **somente** para resposta explícita `BUSY` (não retransmite operações destrutivas se ocorrer timeout).
- Erros específicos: `HuskyLensTimeout`, `HuskyLensBusy`, `HuskyLensNeedPro`, `HuskyLensError`.
- `camera.bad_checksums` registra a quantidade de pacotes rejeitados por checksum.

```python
from huskylens import HuskyLens, HuskyLensTimeout, HuskyLensError
camera = HuskyLens(tx=17, rx=16, timeout=700, retries=1)
try:
    camera.set_algorithm('LINE_TRACKING')
    for linha in camera.get_arrows():
        print(linha.x_origin, linha.y_origin, linha.x_target, linha.y_target)
except HuskyLensTimeout:
    print('Câmera não respondeu')
except HuskyLensError as erro:
    print('Erro de protocolo:', erro)
```

## Limitações reais

- Sem *stream* de vídeo ou leitura dos pixels da câmera: o protocolo original fornece objetos/vetores, não frames crus.
- Não há comandos públicos confirmados para exposição, brilho, foco, idiomas, sensibilidade, menu completo ou atualização de firmware. Essas configurações continuam na câmera.
- O comando `0x3C` é descrito de forma incompleta no documento público. O método experimental segue o handshake mostrado no código Arduino, **não retorna a versão do firmware**.
- `is_pro()` pode variar por firmware e não acrescenta modos à HuskyLens 1.
- Não misturar bibliotecas/protocolos da HuskyLens 2; verifique o mapeamento dos pinos UART e I²C na sua placa.
- Testes automatizados são de **protocolo e comportamento simulado**, não testes elétricos/visuais reais. A integração final depende do firmware da sua câmera.

## Testes no computador

```bash
python -m unittest discover -s tests -v
```

### Referências públicas

- [HuskyLens 1 — protocolo 0.5.1](https://github.com/HuskyLens/HUSKYLENSArduino/blob/master/HUSKYLENS%20Protocol.md)
- [HuskyLens — código Arduino da comunicação](https://github.com/HuskyLens/HUSKYLENSArduino/blob/master/HUSKYLENS/HUSKYLENS.h)
- [HuskyLens — biblioteca Python oficial (não MicroPython)](https://github.com/HuskyLens/HUSKYLENSPython)

**Licença:** MIT — veja [`LICENSE`](LICENSE). Uso, modificação e redistribuição são permitidos, inclusive comercialmente, desde que o aviso de copyright e a licença sejam preservados. Autor indicado na licença: **mosanielbr-hub**. Projeto independente, não oficial da DFRobot/HuskyLens.
