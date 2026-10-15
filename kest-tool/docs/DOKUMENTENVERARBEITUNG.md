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


## Erweiterte Erkennung und Währungsumrechnung

Der Parser erkennt zusätzliche deutsche und englische Feldnamen, umgebrochene
Label-/Wertzeilen, Valuta, Wertpapiernamen, Quellenstaat und Zahlen mit deutschen
oder englischen Tausender-/Dezimaltrennzeichen. Bei fehlenden Pflichtfeldern wird
zusätzlich die alternative PDF-Texterkennung versucht. Widersprüchliche Angaben
bleiben zur Prüfung offen. PDFs über 30 Seiten werden nicht teilweise verarbeitet.

Fehlende Stückzahlen, Stückkurse und bestimmte Bruttobeträge können aus belegten
Werten berechnet werden. Erforderliche, berechnete Werte sind Vorschläge mit
verminderter Konfidenz; sie lösen keine ungeprüfte automatische Buchung aus.
Originalbeträge, Währungen, Quellen und ein Textauszug stehen im Prüfformular
unter **Alle erkannten Angaben und ihre Quellen**.

Belegkurse mit Währungspaar bzw. Gleichung haben Vorrang. Auch inverse Notierungen
werden auf **Fremdwährung je EUR** normalisiert. Gebühren und Quellensteuern in
EUR werden bei Fremdwährungsbuchungen in die Buchungswährung umgerechnet; die
Originalbeträge bleiben im Extraktionsbericht erhalten. Unterschiedliche oder
widersprüchliche Kurse werden nicht stillschweigend übernommen.

Wenn kein eindeutiger Belegkurs vorliegt, können historische EZB-Referenzkurse
bereits während der Verarbeitung ergänzt werden. Maßgeblich ist das sicher erkannte
Buchungsdatum; an Wochenenden/Feiertagen der letzte verfügbare Kurs davor (maximal
sieben Tage). Es werden niemals zukünftige Kurse verwendet. Quelle:
https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html

**Einstellungen → Devisenkurse** steuert den automatischen Internetabruf. Bei
abgeschaltetem Abruf kann ein vorhandener lokaler EZB-Cache weiterhin genutzt
werden. Heruntergeladen wird nur die öffentliche historische Kursdatei; PDF-Inhalte,
Namen und Depotdaten werden nicht übertragen. Quelle und Kursdatum werden mit der
Buchung gespeichert. EZB-Werte bleiben vorläufig und ersetzen keinen belegten
Bankkurs beim Abgleich des tatsächlichen Endbetrags. Nicht unterstützte Währungen
oder fehlende Kurstage bleiben offen. Bei Netzfehlern bleiben erkannte Daten erhalten.

## Gescannte PDFs / lokale OCR

Unter **Einstellungen → Dokumentenerkennung** lässt sich lokale OCR einschalten.
Das Docker-Image enthält Tesseract mit Deutsch und Englisch. Unter Windows müssen
Tesseract und die Sprachdaten zusätzlich installiert sein. Es gibt keinen Cloud-Upload.
OCR wird nur bei fehlendem Text bzw. fehlenden Pflichtfeldern versucht, maximal
acht Seiten je Dokument bei 200 dpi. OCR-Ergebnisse müssen immer mit dem Original
verglichen werden und werden nicht automatisch gebucht.

Nach einem Update: **Dokumente → Alle erneut automatisch prüfen**. Offene Originale
werden mit der neuen Erkennung und den aktuellen EZB-/OCR-Einstellungen erneut
gelesen. Bereits verknüpfte Buchungen werden dabei weder verändert noch dupliziert.
