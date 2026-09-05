# EmbeddPilot V1.5 backend: FastAPI + ingestion + generation + validator.
# The validator gets a REAL toolchain here — arm-none-eabi-gcc (the compile
# judge the V1.5 spec names), host gcc as fallback, and cppcheck so static
# analysis stops reporting "skipped".
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libc6-dev gcc-arm-none-eabi libnewlib-arm-none-eabi \
        libnewlib-dev cppcheck curl ca-certificates \
        # Renode is a .NET application and refuses to start without ICU:
        # "Couldn't find a valid ICU package installed on the system".
        # The slim base image does not carry it, so emulation died at machine
        # start in production while every other stage passed. libicu-dev is
        # used rather than a versioned runtime package so this survives a
        # Debian release bump of the base image.
        libicu-dev \
    && rm -rf /var/lib/apt/lists/*

# V1.8 Part A: arduino-cli + cores so the Arduino target's multi-core compile
# judge runs in the deployed environment too — ESP32-S3 (the engineers' board),
# AVR/Uno, and SAMD (Cortex-M0+). This is a LARGE layer (the esp32 core pulls
# xtensa/riscv toolchains). If a core is ever absent at runtime, arduino_check
# reports that core 'skipped' and finalize() refuses to validate — never a
# silent pass.
RUN curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
        | BINDIR=/usr/local/bin sh \
    && arduino-cli config init \
    && arduino-cli config add board_manager.additional_urls \
        https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json \
    && arduino-cli core update-index \
    && arduino-cli core install arduino:avr \
    && arduino-cli core install arduino:samd \
    && arduino-cli core install esp32:esp32 \
    && rm -rf /tmp/*

# V2 WS5: Renode, so the emulation check can actually RUN the generated firmware
# here rather than reporting "skipped". Without it the deployed product could
# compile an application but never prove it works — and "working (emulated)" is
# the whole V2 claim. Self-contained portable build; no mono/dotnet needed.
RUN curl -fsSL -o /tmp/renode.tar.gz \
        https://github.com/renode/renode/releases/download/v1.16.1/renode-1.16.1.linux-portable-dotnet.tar.gz \
    && mkdir -p /opt/renode \
    && tar -xzf /tmp/renode.tar.gz -C /opt/renode --strip-components=1 \
    && ln -s /opt/renode/renode /usr/local/bin/renode \
    && rm -rf /tmp/renode.tar.gz

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api api
COPY generation generation
COPY validator validator
COPY ingestion ingestion
COPY schema schema
# V2: the end-to-end pipeline lives in its own top-level package (it may not sit
# in generation/, which the contamination guard forbids from importing
# validator/). Without this the /api/v2/* routes ImportError at request time.
COPY orchestration orchestration
# V2 WS4: the linker script the generated firmware is built against. It is a
# build input, not a test fixture, even though it lives under tests/.
COPY tests/fixtures/emulation/stm32f4.ld tests/fixtures/emulation/stm32f4.ld
COPY artifacts/bme280-extracted-map.json \
     artifacts/w25q64-extracted-map.json \
     artifacts/esp32-i2c-extracted-map.json \
     artifacts/bmp180-extracted-map.json \
     artifacts/
# V1.7 cached MCU maps (the RM PDFs are gitignored and not in the image, so the
# committed cache is the only source of MCU maps here — ship it).
COPY artifacts/mcu_cache artifacts/mcu_cache

# Railway injects PORT
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
