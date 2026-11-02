# Solar charging controller: setup

The controller runs from `.github/workflows/controller.yml` every 5 minutes. It starts in
**dry-run mode**: it reads PV power and logs what it would do, without sending car commands.

Scheduled workflows only run from the default branch (`main`), so nothing runs until this is merged.

**Never commit private values.** Everything below marked *secret* goes in
Settings → Secrets and variables → Actions → **Secrets**. Logs are public.

## 1. Key pair (on your own computer)

```
openssl ecparam -name prime256v1 -genkey -noout -out private-key.pem
openssl ec -in private-key.pem -pubout -out public-key.pem
```

- Commit `public-key.pem` as `.well-known/appspecific/com.tesla.3p.public-key.pem`.
- Secret `TESLA_PRIVATE_KEY`: the full contents of `private-key.pem`. Then keep the file offline or delete it.

## 2. Tesla developer app (developer.tesla.com)

- Allowed origin: `https://alexmoggo.github.io`
- Redirect URI: `https://alexmoggo.github.io/`
- Scopes: `vehicle_device_data`, `vehicle_cmds`, `vehicle_charging_cmds`
- Add a payment method and set the billing limit to $1 (the default 0 disables the app).
- Secret `TESLA_CLIENT_ID`. Keep the client secret local only; Actions does not need it.

On your computer (Python 3.10+, `pip install requests`):

```
export TESLA_CLIENT_ID=...  TESLA_CLIENT_SECRET=...
python scripts/tesla_setup.py register   # after the public key is live on Pages
python scripts/tesla_setup.py auth       # prints the TESLA_TOKENS value
```

- Secret `TESLA_TOKENS`: the JSON printed by `auth`.
- Secret `TESLA_VIN`: the car's VIN.
- Pair the key: open `https://tesla.com/_ak/alexmoggo.github.io` on the phone with the Tesla app.

## 3. iSolarCloud developer app (developer-api.isolarcloud.com)

- Create an OAuth2 app with redirect URL `https://alexmoggo.github.io/` and wait for approval.
- Secrets `SUNGROW_APPKEY` and `SUNGROW_SECRET_KEY`.

```
export SUNGROW_APPKEY=...  SUNGROW_SECRET_KEY=...  SUNGROW_APP_ID=...
python scripts/sungrow_setup.py
```

- Secret `SUNGROW_TOKENS`: the JSON printed.
- Secret `SUNGROW_PLANT_ID`: the plant ID printed.
- Compare the two printed power values with the iSolarCloud app. If `83002` matches better than
  `83033`, set the variable `SUNGROW_POWER_POINT` to `83002`.

## 4. Token rotation

Tesla and iSolarCloud refresh tokens rotate, so the workflow must save new ones. Create a
**fine-grained personal access token** limited to this repository with
**Repository permissions → Secrets: Read and write**. Store it as secret `GH_SECRETS_PAT`.

## 5. Variables (Settings → Secrets and variables → Actions → Variables)

| Variable | Default | Purpose |
|---|---|---|
| `CONTROLLER_LIVE` | unset (dry run) | Set to `true` to send car commands |
| `HOUSE_LOAD_W` | `1000` | Assumed house load |
| `MIN_AMPS` | `5` | Car minimum charge current (to be confirmed) |
| `SUNGROW_POWER_POINT` | `83033` | iSolarCloud data point for PV power |

## 6. Dry run, then live

1. Run the workflow manually (Actions → Solar charging controller → Run workflow) and check the log line.
2. Leave it in dry run for 2 to 3 days. Each run logs time, PV, target, action and the Fleet API estimate.
3. Set `CONTROLLER_LIVE=true` only after review.
