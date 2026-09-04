#!/usr/bin/env bash
#
# RAGFlow local enterprise deployment (v0.26.4)
# Linux serverda ishga tushiring:
#     chmod +x deploy.sh
#     ./deploy.sh
#
# Sozlamalar: ragflow.conf faylida. Parollar avtomatik generatsiya qilinadi.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Sozlamalarni yuklash ---
CONF="$SCRIPT_DIR/ragflow.conf"
[ -f "$CONF" ] || { echo "XATO: ragflow.conf topilmadi ($CONF)"; exit 1; }
# shellcheck disable=SC1090
source "$CONF"

RAGFLOW_VERSION="${RAGFLOW_VERSION:-v0.26.4}"
REPO_DIR="$SCRIPT_DIR/ragflow"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

echo "==> 1/6 Talablarni tekshirish"
for bin in git docker openssl; do
  command -v "$bin" >/dev/null || { echo "XATO: '$bin' o'rnatilmagan"; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "XATO: 'docker compose' (v2) kerak"; exit 1; }
if [ "${DEVICE:-cpu}" = "gpu" ]; then
  command -v nvidia-smi >/dev/null 2>&1 \
    || echo "    OGOHLANTIRISH: nvidia-smi topilmadi — NVIDIA drayver o'rnatilganmi?"
  if ! $SUDO docker info 2>/dev/null | grep -qi nvidia; then
    echo "    OGOHLANTIRISH: Docker'da NVIDIA runtime ko'rinmadi."
    echo "      NVIDIA Container Toolkit kerak: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
  fi
fi
echo "    OK"

echo "==> 2/6 Kernel parametri (Elasticsearch uchun vm.max_map_count)"
CUR="$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)"
if [ "$CUR" -lt 262144 ]; then
  $SUDO sysctl -w vm.max_map_count=262144 >/dev/null
  if ! grep -qs "vm.max_map_count" /etc/sysctl.conf; then
    echo "vm.max_map_count=262144" | $SUDO tee -a /etc/sysctl.conf >/dev/null
  fi
  echo "    o'rnatildi: 262144 (qayta ishga tushishda ham saqlanadi)"
else
  echo "    allaqachon yetarli: $CUR"
fi

echo "==> 3/6 RAGFlow ${RAGFLOW_VERSION} klonlash"
if [ ! -d "$REPO_DIR" ]; then
  git clone --depth 1 --branch "$RAGFLOW_VERSION" \
    https://github.com/infiniflow/ragflow.git "$REPO_DIR"
else
  echo "    mavjud: $REPO_DIR (qayta klonlanmadi)"
fi

ENV_FILE="$REPO_DIR/docker/.env"
[ -f "$ENV_FILE" ] || { echo "XATO: $ENV_FILE topilmadi"; exit 1; }

echo "==> 4/6 Konfiguratsiya (.env)"
MARKER="# --- ragflow.conf tomonidan sozlangan ---"
if grep -qs "$MARKER" "$ENV_FILE"; then
  echo "    .env allaqachon sozlangan (mavjud parollar saqlanadi). O'tkazib yuborildi."
else
  cp "$ENV_FILE" "$ENV_FILE.bak"

  set_env() {
    local key="$1" val="$2" esc
    esc="$(printf '%s' "$val" | sed -e 's/[\/&|]/\\&/g')"
    if grep -qE "^${key}=" "$ENV_FILE"; then
      sed -i "s|^${key}=.*|${key}=${esc}|" "$ENV_FILE"
    else
      printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
    fi
  }

  # --- Non-secret sozlamalar (ragflow.conf dan) ---
  set_env RAGFLOW_IMAGE "infiniflow/ragflow:${RAGFLOW_VERSION}"
  set_env DOC_ENGINE    "${DOC_ENGINE:-elasticsearch}"
  set_env DEVICE        "${DEVICE:-cpu}"
  set_env TEI_MODEL     "${TEI_MODEL:-BAAI/bge-m3}"
  set_env TZ            "${TZ:-Asia/Tashkent}"
  set_env MEM_LIMIT     "${MEM_LIMIT:-8589934592}"

  # --- Local embedding (TEI) profilini yoqish ---
  # DEVICE=gpu bo'lsa tei-gpu, aks holda tei-cpu profilini yoqadi.
  # Upstream .env dagi mos qatorni comment'dan chiqaradi.
  if [ "${ENABLE_LOCAL_EMBEDDING:-true}" = "true" ]; then
    if [ "${DEVICE:-cpu}" = "gpu" ]; then TEI_PROFILE="tei-gpu"; else TEI_PROFILE="tei-cpu"; fi
    sed -i "s|^# *COMPOSE_PROFILES=\${COMPOSE_PROFILES},${TEI_PROFILE}|COMPOSE_PROFILES=\${COMPOSE_PROFILES},${TEI_PROFILE}|" "$ENV_FILE"
    if ! grep -qs "^COMPOSE_PROFILES=\${COMPOSE_PROFILES},${TEI_PROFILE}" "$ENV_FILE"; then
      echo "COMPOSE_PROFILES=\${COMPOSE_PROFILES},${TEI_PROFILE}" >> "$ENV_FILE"
    fi
    echo "    embedding profili: ${TEI_PROFILE} (model: ${TEI_MODEL:-BAAI/bge-m3})"
  fi

  # --- Xavfsiz random parollar ---
  set_env MYSQL_PASSWORD   "$(openssl rand -hex 16)"
  set_env MINIO_PASSWORD   "$(openssl rand -hex 16)"
  set_env REDIS_PASSWORD   "$(openssl rand -hex 16)"
  set_env ELASTIC_PASSWORD "$(openssl rand -hex 16)"

  printf '\n%s\n' "$MARKER" >> "$ENV_FILE"
  echo "    .env yozildi (zaxira nusxa: $ENV_FILE.bak)"
fi

echo "==> 5/6 Konteynerlarni ishga tushirish (birinchi marta image yuklanadi, biroz kutadi)"
( cd "$REPO_DIR/docker" && $SUDO docker compose up -d )

echo "==> 6/6 Holat"
( cd "$REPO_DIR/docker" && $SUDO docker compose ps )

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

============================================================
 RAGFlow ishga tushdi.

   Web UI:     http://${IP:-<server-ip>}
               (birinchi ro'yxatdan o'tgan foydalanuvchi = admin)
   HTTP API:   http://${IP:-<server-ip>}:9380
   Embedding:  local TEI (${TEI_MODEL:-BAAI/bge-m3})
               -> birinchi ishga tushishda model yuklanadi;
                  "docker compose logs -f tei" bilan kuzating.

 Keyingi qadamlar:
   1) Web UI -> akkaunt yarating (birinchi = admin).
   2) connect-llm.md bo'yicha gemma LLM'ni ulang.
   3) Knowledge base yarating, o'zbekcha hujjat yuklang, parse qiling.
   4) API kalitini oling -> test_api.py bilan sinang.

 Foydali:
   Loglar:      cd ragflow/docker && docker compose logs -f ragflow
   To'xtatish:  cd ragflow/docker && docker compose down
   Parollar:    ragflow/docker/.env  (random generatsiya qilingan)
============================================================
EOF
