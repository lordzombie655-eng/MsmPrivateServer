# MSM Private Server (Render / Railway)

Servidor privado de My Singing Monsters optimizado para la nube.

## Importante: dominio público

En local el servidor usaría `127.0.0.1`. En **Render** o **Railway** debe usar tu dominio público.

### Render

1. Variables de entorno:
   - `PUBLIC_HOST` = `tu-app.onrender.com`  (sin https://, sin puerto)
   - `MAX_PLAYERS` = `500`
   - `LOG_LEVEL` = `warning`

2. Render también define solo `RENDER_EXTERNAL_HOSTNAME` — el servidor la detecta.

3. Build / Start:
   ```
   Build:  pip install -r requirements.txt
   Start:  python server.py
   ```

### Railway

- `PUBLIC_HOST` = `tu-app.up.railway.app`
- o usa `RAILWAY_PUBLIC_DOMAIN` (automático)

**Nunca** pongas `:8080` ni `:9933` en el dominio público. HTTPS/WSS van por el **443** del proveedor.

## Comprobar que ya no es local

Abre en el navegador:

```
https://TU-DOMINIO/
https://TU-DOMINIO/status
https://TU-DOMINIO/auth.php
```

Debe verse algo como:

```json
"public_host": "tu-app.onrender.com",
"public": true,
"base_url": "https://tu-app.onrender.com",
"serverIp": "tu-app.onrender.com"
```

Si `serverIp` es `127.0.0.1`, falta `PUBLIC_HOST` o no se redeployó.

## Cliente (APK de private server)

```
BBB_AUTH_SERVER=https://tu-app.onrender.com
BBB_AUTH2_SERVER=https://tu-app.onrender.com
```

Sin puerto.

## Ejemplo con tu Render actual

```
PUBLIC_HOST=msm-private-server-9e32.onrender.com
BBB_AUTH_SERVER=https://msm-private-server-9e32.onrender.com
BBB_AUTH2_SERVER=https://msm-private-server-9e32.onrender.com
```
