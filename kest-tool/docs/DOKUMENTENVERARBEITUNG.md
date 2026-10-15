# Dokumentenverarbeitung: sicherer Import und Prüfung

## Browser-Import (empfohlen)

Unter **Dokumente importieren** können Sie bei *Upload-Art auswählen* zwischen **Einzeldateien / ZIP** und **Kompletten Ordner** wechseln. PDF, CSV, TXT, XLSX und ZIP werden angenommen; Ordner dürfen Unterordner und ZIP-Dateien enthalten.

ZIP-Dateien werden nur bis zu zwei zusätzlichen Archiv-Ebenen entpackt. Maximal 2.000 Einträge, 50 MB je entpacktem Eintrag und 500 MB entpackte Daten pro ZIP beziehungsweise Browser-Upload-Stapel werden verarbeitet. Passwortgeschützte und defekte ZIPs werden gemeldet. Pfadbestandteile aus ZIP-Archiven werden nicht zum Schreiben auf der Festplatte verwendet.

Identische Originaldateien werden über SHA-256 erkannt. Eine Dublette der Datei wird nicht erneut verarbeitet. Neue PDF-Dateien werden zunächst analysiert, um Broker, Art, Datum und Beträge zuzuordnen. Nur widerspruchsfrei erkannte Einzelbuchungen können automatisch übernommen werden. Unvollständige Dokumente und **ähnliche (nicht identische) Buchungen** werden zur Prüfung zurückgestellt; sie verändern bis zur manuellen Übernahme die Steuerberechnung nicht.

## Dokumentenprüfung

Unter **Dokumente → Zu prüfen** öffnen Sie einen Eintrag und vergleichen den Prüfbericht mit dem Original. Bei Bedarf nutzen Sie **PDF-Analyse aktualisieren**. Diese Aktion liest den Beleg neu aus, löscht aber keine bestehende Buchung. Bei einem Fehler bleibt die vorher gespeicherte Analyse erhalten.

Für die gemeinsame Änderung von Dokumentmetadaten gibt es unter Dokumente eine Tabelle mit Markierkästchen. Änderungen betreffen ausschließlich aktivierte Felder; vorhandene Buchungen bleiben unverändert.

## Fehlerdiagnose

Unter **Einstellungen → Diagnose und Fehlerbericht** können Sie einen ZIP-Bericht erzeugen. Er enthält Versionsangaben, Fehlerkennungen, Zeitpunkte und Fehlertypen, jedoch keine PDF-Inhalte, Kontodaten, Zugangsdaten oder vollständigen Stacktraces. Fehler bei der PDF-Verarbeitung werden nach Möglichkeit einzeln erfasst, damit die übrigen Dokumente weiterbearbeitet werden.

## Serverseitige Ordner (optional)

Der erweiterte **Serverordner-Import** kann Dateien aus dem Docker-Container/Proxmox-LXC lesen, nicht direkt aus einem Windows-Ordner. Er ist standardmäßig deaktiviert. Nur der Administrator kann ihn über die Container-Umgebungsvariable `KEST_ALLOW_SERVER_FOLDER_IMPORT=1` einschalten. Geben Sie dafür keine weitreichenden Serververzeichnisse frei. Der Browser-Ordnerupload benötigt diese Einstellung **nicht**.

## Betrieb und Datenschutz

Vor einem Versionswechsel sollte ein **Backup** des Ordners `data/kest` erstellt werden. Die Anwendung verwendet lokale Dateien und eine SQLite-Datenbank. Verwenden Sie dieselbe Datenbank nicht gleichzeitig aus zwei unabhängigen Installationen. Erkennungsheuristiken sind **keine steuerliche Verifikation**: Originalbelege, Fondsstatus, Broker-Steuerabzug und Rechenergebnisse weiterhin kontrollieren. Der Broker-PDF-Parser ist hauptsächlich mit synthetischen Musterdokumenten getestet; Layoutänderungen der Broker benötigen reale Testfälle ohne private Daten.
