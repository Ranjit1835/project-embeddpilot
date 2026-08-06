/* EmbeddPilot compile-judge STUB — not the real FreeRTOS header.
 * Declarations/macros only; see ../esp_err.h for the rationale. */
#ifndef EMBEDDPILOT_STUB_FREERTOS_H
#define EMBEDDPILOT_STUB_FREERTOS_H

#include <stdint.h>

typedef uint32_t TickType_t;

#define portTICK_PERIOD_MS 1
#define portMAX_DELAY 0xffffffffUL
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
#define pdTRUE 1
#define pdFALSE 0

#endif
