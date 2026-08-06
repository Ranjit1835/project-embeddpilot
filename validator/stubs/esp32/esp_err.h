/* EmbeddPilot compile-judge STUB — not the real ESP-IDF header.
 * Provides just enough of the ESP-IDF surface for the generated driver +
 * example to compile clean under -Wall -Wextra -Werror. The judge only
 * COMPILES (-c), never links, so declarations are sufficient. This lets us
 * give esp32 targets real syntax/warning coverage without shipping the full
 * Xtensa toolchain + IDF in the container. */
#ifndef EMBEDDPILOT_STUB_ESP_ERR_H
#define EMBEDDPILOT_STUB_ESP_ERR_H

typedef int esp_err_t;

#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_TIMEOUT 0x107
#define ESP_ERR_INVALID_STATE 0x103

const char *esp_err_to_name(esp_err_t code);

#endif
