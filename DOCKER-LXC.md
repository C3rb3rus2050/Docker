# Docker im Proxmox-LXC

Die aktuelle Anwendung besteht aus dem KESt-Tool und einem Caddy-Proxy.
Installation, SSH-Tunnel, Datenhaltung und Updates sind in [WEB-DEPLOY.md](WEB-DEPLOY.md) beschrieben.

Der LXC muss Docker unterstützen. Die Weboberfläche ist standardmäßig nur auf
`127.0.0.1:8080` am Docker-Host erreichbar; der Zugriff erfolgt über einen SSH-Tunnel.

Frühere Anleitungen mit Broker-Collector, Chromium und noVNC gelten nicht mehr.
Broker-Dokumente werden manuell heruntergeladen und im KESt-Tool importiert.
