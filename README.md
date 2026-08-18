# MSM Private Server (reorganizado)

Servidor privado para **My Singing Monsters**.

## Estructura

```
msm_reorg/
├── Config.json          # Configuración del servidor (editable)
├── Data/                # TODOS los JSON del juego (datos)
├── players/             # Datos de jugadores (se crea solo)
├── server.py            # Script principal (ejecutar este)
├── multi_instance.py    # Lanza varias instancias (versiones/servidores)
├── msm_*.py             # Módulos internos del juego
└── protocol / handlers / store etc. (módulos de soporte)
```

Hay **más de 4 scripts Python** porque el juego tiene mucha lógica (monstruos, islas, structures, etc.).  
Los que importan al usuario son:

1. `server.py`          → servidor principal
2. `multi_instance.py`  → varias versiones/servidores a la vez
3. Los módulos `msm_*.py` (internos, no hace falta tocarlos)
4. `Config.json`        → configuración

Todos los **JSON de datos** están en la carpeta **`Data/`**.

## Requisitos

```bash
pip install fastapi uvicorn pycryptodome
```

## Uso rápido (1 servidor)

```bash
cd msm_reorg
python server.py
```

Edita `Config.json` para cambiar:

| Clave            | Descripción                          | Ejemplo    |
|------------------|--------------------------------------|------------|
| `host`           | IP de escucha                        | `0.0.0.0`  |
| `http_ports`     | Puertos HTTP                         | `[5050]`   |
| `server_id`      | ID del servidor                      | `1`        |
| `max_players`    | Límite de personas conectadas        | `30`       |
| `data_dir`       | Carpeta de los JSON                  | `Data`     |
| `players_dir`    | Carpeta de partidas de jugadores     | `players`  |
| `log_level`      | info / debug / warning               | `info`     |
| `server_name`    | Nombre del servidor                  | `...`      |

`max_players = 0` o quitar la clave = sin límite.

## Varias versiones / varios servidores a la vez

Cada instancia actúa como **otro servidor** (puertos y `server_id` distintos, jugadores separados).

```bash
python multi_instance.py
```

Por defecto arranca 4 instancias:

| Nombre     | Puerto HTTP | server_id | max_players | Carpeta jugadores     |
|------------|-------------|-----------|-------------|-----------------------|
| MSM_Main   | 5050        | 1         | 30          | players/main          |
| MSM_Alt1   | 5051        | 2         | 15          | players/alt1          |
| MSM_Alt2   | 5052        | 3         | 10          | players/alt2          |
| MSM_Test   | 5053        | 4         | 5           | players/test          |

Puedes editar la lista `INSTANCES` dentro de `multi_instance.py` para añadir/quitar versiones o cambiar límites.

Los datos del juego (`Data/`) se comparten; los jugadores de cada instancia están separados.

## Notas

- El cliente debe apuntar al host/puerto de la instancia que quieras usar.
- `server_id` diferente hace que el cliente lo trate como servidor distinto.
- Para datos específicos por versión (si algún día quieres JSON distintos), cambia `data_dir` en la config de esa instancia a otra carpeta.

## Créditos

Basado en Next Private Server.
