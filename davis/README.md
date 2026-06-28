# Davis Vantage Vue

**Status: Planned — hardware not yet available.**

The Davis Vantage Vue sensor suite transmits on 868 MHz ISM band (EU frequency plan). Reception requires an **ESP32 + CC1101** receiver running ESPHome firmware, which handles RF decoding and MQTT publishing directly.

MQTT topics will follow the project convention:

```
weatherdatalogger/davis-<id>/<sensor>
```

This directory will hold ESPHome YAML configuration and any supporting scripts once the hardware arrives.
