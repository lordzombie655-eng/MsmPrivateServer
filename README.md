# MSM Private Server — Railway + optimizado

Servidor privado de **My Singing Monsters**, optimizado para muchas conexiones y listo para **Railway**.

## Características

- **1 solo puerto fijo** (por defecto `9933`; en Railway usa el `$PORT` automático)
- **Hasta 500 jugadores** por defecto (`max_players`, configurable)
- Preload de todos los JSON de `Data/` en memoria al arrancar
- Caché de jugadores en memoria
- `orjson` + `uvloop` cuando están disponibles
- Logging reducido (solo warning) para no saturar bajo carga
- Uvicorn con `limit_concurrency=2000` y backlog alto

---

## Desplegar en Railway (recomendado)

### 1. Sube el código

Opción A — desde GitHub:
1. Crea un repo y sube **todo** el contenido de esta carpeta (`server.py`, `Data/`, `requirements.txt`, etc.).
2. En [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.

Opción B — CLI:
```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

### 2. Configuración en Railway

Railway asigna el puerto con la variable **`PORT`**. El servidor la detecta solo y escucha ahí (un solo puerto).

Variables opcionales (Settings → Variables):

| Variable        | Descripción                     | Ejemplo        |
|-----------------|---------------------------------|----------------|
| `MAX_PLAYERS`   | Límite de conexiones simultáneas| `500`          |
| `LOG_LEVEL`     | `warning` / `info` / `debug`    | `warning`      |
| `SERVER_ID`     | ID del servidor                 | `1`            |
| `SERVER_NAME`   | Nombre visible                  | `Mi MSM`       |
| `PUBLIC_HOST`   | Dominio público (sin https://)  | `xxx.up.railway.app` |

### 3. Generar dominio público

En el servicio → **Settings** → **Networking** → **Generate Domain**.

Copia el dominio (ej: `msm-production-xxxx.up.railway.app`).

### 4. Cliente / APK

El cliente debe apuntar al dominio de Railway (HTTP + WebSocket en el mismo host/puerto que Railway expone).  
Railway termina TLS en el edge; el contenedor recibe HTTP en `$PORT`.

---

## Ejecutar en local

```bash
pip install -r requirements.txt
python server.py
```

Puerto fijo por defecto: **9933**.

Cambia en `Config.json`:
```json
{
  "port": 9933,
  "http_ports": [9933],
  "game_port": 9933,
  "max_players": 500,
  "log_level": "warning"
}
```

---

## Optimizaciones aplicadas

1. **Un solo puerto** — más simple y compatible con Railway.
2. **Preload de DB** — todos los JSON de `Data/` en RAM al inicio.
3. **Caché de jugadores** — menos lecturas de disco.
4. **orjson** — serialización JSON más rápida.
5. **uvloop** — event loop más rápido (Linux).
6. **Logging en warning** — menos I/O bajo carga.
7. **limit_concurrency=2000** + backlog alto en Uvicorn.
8. **max_players=500** por defecto (sube o baja con la variable `MAX_PLAYERS`).

Si necesitas aún más capacidad: sube el plan de Railway (más RAM/CPU) y aumenta `MAX_PLAYERS`.

---

## Estructura

```
├── server.py           # Entrada principal
├── Config.json         # Config local
├── requirements.txt    # Dependencias
├── Procfile            # Railway start
├── railway.toml
├── Data/               # Todos los JSON del juego
├── players/            # Datos de jugadores
└── msm_*.py            # Módulos del juego
```

## Requisitos

Python 3.10+

```
fastapi, uvicorn[standard], websockets, pycryptodome, orjson, uvloop
```
