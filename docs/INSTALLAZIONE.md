# Installazione di Aurora sul server aziendale

Questa procedura porta una macchina Windows vuota fino ad Aurora in esercizio:
Python, PostgreSQL, il programma, il certificato, il servizio che riparte da
solo, la copia notturna.

**E' scritta per essere seguita alla lettera**, da qualcuno che di Aurora non
sa niente. Ogni passo finisce con una verifica: se la verifica non da' il
risultato scritto, ci si ferma li' e si risolve, invece di andare avanti
sperando. Il tempo totale, senza intoppi, e' di **circa due ore**, di cui
un'ora e mezza di attese.

> **Prima di cominciare, una cosa che fa risparmiare mezza giornata.** Le
> richieste all'ufficio informatico (sezione 3) hanno tempi loro, che non
> dipendono da noi. Vanno **mandate prima**, non nel momento in cui servono.

---

## Indice

| Sezione | Che cosa si fa | Serve l'amministratore? |
|---|---|---|
| 0 | Che macchina serve | no |
| 1 | Python | si |
| 2 | PostgreSQL | si |
| 3 | Le richieste all'ufficio informatico | — |
| 4 | Aurora: i file e l'ambiente | no |
| 5 | Il database di Aurora | si |
| 6 | Il certificato e l'https | si |
| 7 | Prima accensione, a mano | no |
| 8 | La configurazione guidata | no |
| 9 | Il servizio di Windows | si |
| 10 | L'irrobustimento del registro | si (password di `postgres`) |
| 11 | La copia notturna | si |
| 12 | Le verifiche finali | no |
| 13 | L'ambiente di prova sulla stessa macchina | si |
| 14 | Che cosa consegnare a chi amministrera' | — |

---

## 0. Che macchina serve

| | Minimo | Consigliato |
|---|---|---|
| Sistema | Windows Server 2019 o Windows 10 | Windows Server 2022 |
| Memoria | 4 GB | 8 GB |
| Processore | 2 core | 4 core |
| Disco di sistema (C:) | 40 GB liberi | 80 GB |
| Disco dell'archivio | 200 GB | 1 TB, su un disco **diverso** da C: |
| Disco delle copie | quanto l'archivio | su un **terzo** disco, o su una condivisione di rete |

**Perche' tre dischi e non uno.** Il primo e' il sistema. Il secondo tiene
l'archivio dei documenti, che e' il patrimonio dell'azienda e cresce: tenerlo
sul disco di sistema vuol dire che il giorno in cui si riempie si ferma anche
Windows. Il terzo tiene le copie di sicurezza, e sta a parte per la ragione
piu' semplice di tutte: **una copia sullo stesso disco dell'originale protegge
dallo sbaglio di una persona e da nient'altro**, e il guasto che si teme di
piu' e' proprio quello del disco.

Se i dischi sono due invece di tre, il secondo tiene l'archivio e le copie
vanno su una condivisione di rete. Se il disco e' uno solo, Aurora funziona
lo stesso e la pagina di diagnostica lo dira': va messo in preventivo.

**Aurora non ha bisogno di internet.** Non lo usa mai, tranne che per leggere
la casella aziendale se la si collega (sezione 3). Serve pero' **durante
l'installazione**, per scaricare Python, PostgreSQL e le librerie: se il
server e' isolato, si prepara tutto su un'altra macchina e si portano i file
con una chiavetta (vedi la nota alla fine della sezione 4).

---

## 1. Python

**Va installata la stessa versione della macchina di sviluppo: Python 3.14.6.**
Non "3.14 qualcosa": la stessa. Le versioni bloccate in `requirements.txt`
sono state provate con quella, e una versione diversa vuol dire librerie
compilate diverse.

### 1.1 Scaricare

Da <https://www.python.org/downloads/release/python-3146/>, il file
**Windows installer (64-bit)**.

### 1.2 Installare

Eseguire l'installatore **come amministratore** e, nella prima schermata:

- spuntare **"Add python.exe to PATH"** (in fondo alla finestra);
- premere **"Customize installation"**, non "Install Now";
- lasciare tutte le spunte come sono e premere Avanti;
- nella schermata successiva spuntare **"Install Python 3.14 for all users"**.
  Senza, Python finisce nel profilo dell'utente che sta installando, e il
  servizio - che gira con un altro utente - non lo troverebbe;
- percorso: lasciare `C:\Program Files\Python314`.

### 1.3 Verifica

Aprire un PowerShell **nuovo** (quello aperto prima dell'installazione non
conosce ancora il PATH) e scrivere:

```powershell
python --version
```

Deve rispondere esattamente:

```
Python 3.14.6
```

Se risponde qualcos'altro, o "non e' riconosciuto come comando", il PATH non
e' stato sistemato: si riesegue l'installatore, si sceglie "Modify" e si
spunta la casella.

---

## 2. PostgreSQL

Aurora usa **PostgreSQL 18**. La procedura completa, schermata per schermata,
sta gia' in `scripts/setup_postgres.md`, **parte A**: va seguita quella. Qui
ci sono solo le tre cose che su un server aziendale si decidono in modo
diverso dallo sviluppo.

**La password di `postgres` va scelta lunga e messa al sicuro.** E' la chiave
di tutto il database. Va scritta nel gestore delle password dell'azienda, non
su un foglietto e non in un file sul server. Serve tre volte in tutto: adesso,
nella sezione 10, e il giorno di un ripristino.

**La cartella dei dati va sul disco dell'archivio, non su C:.** Nella
schermata "Data Directory" dell'installatore si scrive `D:\PostgreSQL\data`
(o la lettera del disco dedicato). E' la cartella che cresce.

**La porta resta 5432.** Non va aperta nel firewall: Aurora e PostgreSQL
girano sulla stessa macchina e si parlano da dentro. L'unica porta che si apre
e' quella di Aurora (sezione 3).

### 2.1 Verifica

```powershell
Get-Service -Name postgresql*
```

Deve comparire una riga con `Status: Running` e un nome che comincia per
`postgresql-x64-18`. **Annotare quel nome per esteso**: e' quello che si
scrive nelle istruzioni di chi amministrera'.

---

## 3. Le richieste all'ufficio informatico

Sono cinque, e vanno mandate **adesso**, perche' hanno tempi che non
dipendono da noi. Il testo da copiare in una email e' qui sotto.

> **Oggetto: Aurora — richieste per la messa in esercizio sul server NOMESERVER**
>
> Buongiorno,
> stiamo installando sul server **NOMESERVER** il gestionale interno Aurora
> (documentazione tecnica di progetto). Gira in rete locale, non espone niente
> verso internet e non usa servizi esterni. Ci servono cinque cose.
>
> **1. Esclusione dell'antivirus su tre cartelle.**
> Aurora scrive e rilegge migliaia di file al giorno, e ne calcola l'impronta
> mentre arrivano. Con la scansione in tempo reale attiva su quelle cartelle il
> caricamento di un documento da 200 MB passa da qualche secondo a qualche
> minuto, e in piu' l'antivirus puo' tenere aperto un file mentre il programma
> lo sta spostando, facendo fallire il salvataggio.
> Le cartelle da escludere sono:
>
>     D:\Aurora\storage        l'archivio dei documenti
>     D:\PostgreSQL\data       i file del database
>     E:\AuroraCopie           le copie di sicurezza
>
> Sono cartelle in cui **non si esegue niente**: contengono solo dati, e i file
> hanno per nome un'impronta esadecimale, senza estensione. Il rischio di
> escluderle e' basso; il costo di non escluderle si vede tutti i giorni.
>
> **2. Percorsi lunghi abilitati.**
> Windows, di partenza, rifiuta i percorsi oltre 260 caratteri. L'archivio di
> Aurora e' annidato e i nomi dei file sono impronte lunghe: con i percorsi
> lunghi disattivati alcuni salvataggi falliscono, e falliscono in modo
> difficile da capire. Si abilita con:
>
>     Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
>       -Name LongPathsEnabled -Value 1
>
> e richiede un riavvio. In alternativa: Criteri di gruppo → Configurazione
> computer → Modelli amministrativi → Sistema → Filesystem → **Abilita percorsi
> Win32 lunghi**.
>
> **3. Apertura della porta 8000 in entrata, solo dalla rete interna.**
> E' la porta su cui Aurora risponde. Va aperta **solo** dalla sottorete
> dell'ufficio, non da tutto il dominio e non da internet:
>
>     New-NetFirewallRule -DisplayName "Aurora (HTTPS)" -Direction Inbound `
>       -Protocol TCP -LocalPort 8000 -Action Allow `
>       -RemoteAddress 192.168.10.0/24
>
> (la sottorete va sostituita con quella vera dell'ufficio tecnico)
>
> **4. Una destinazione per le copie di sicurezza.**
> Ci serve una cartella su un disco o su una condivisione di rete **diversi**
> dal disco del server, con almeno lo spazio dell'archivio, su cui l'utente di
> servizio di Aurora possa scrivere. Se e' una condivisione, ci serve il
> percorso UNC (`\\nas\backup\aurora`) e le credenziali con cui raggiungerla.
>
> **5. Un certificato per il nome del server.**
> Aurora deve parlare in https: senza, le password di chi entra attraversano la
> rete in chiaro. Ci serve un certificato per il nome con cui il server viene
> raggiunto (per esempio `aurora.azienda.local`), rilasciato dalla vostra
> autorita' interna, **in formato PFX con la chiave privata**. Se l'autorita'
> interna e' gia' distribuita ai computer dell'ufficio, i browser lo
> riconosceranno senza avvisi.
>
> Grazie.

**Se serve anche la casella di posta aziendale**, c'e' un secondo documento
gia' scritto e piu' dettagliato: `docs/RICHIESTA_IT.md`. Quello riguarda
Microsoft 365 ed e' indipendente da questo.

---

## 4. Aurora: i file e l'ambiente

### 4.1 Le cartelle

```powershell
New-Item -ItemType Directory -Force C:\Aurora
New-Item -ItemType Directory -Force D:\Aurora\storage
New-Item -ItemType Directory -Force E:\AuroraCopie
```

`C:\Aurora` e' il programma; `D:\Aurora\storage` e' l'archivio dei documenti;
`E:\AuroraCopie` sono le copie di sicurezza. **I tre percorsi si scrivono nel
file `.env` alla sezione 4.4**: se sulla macchina i dischi hanno altre
lettere, si cambiano li' e non si cambia niente d'altro.

### 4.2 Portare il programma

Il codice sorgente si copia dentro `C:\Aurora`: dal repository git
dell'azienda, oppure copiando la cartella `aurora/` da una chiavetta.

**Quello che non va copiato** (e che comunque non e' in git): la cartella
`.venv`, il file `.env`, il contenuto di `storage/`, `logs/` e `backup/`.

Verifica:

```powershell
cd C:\Aurora
Test-Path .\app\main.py, .\requirements.txt, .\.env.example
```

Devono rispondere tre `True`.

### 4.3 L'ambiente virtuale e le librerie

```powershell
cd C:\Aurora
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> **Se PowerShell rifiuta di eseguire `Activate.ps1`** («l'esecuzione di script
> e' disabilitata»), si usa `.\.venv\Scripts\activate.bat`, che funziona
> sempre. Non serve cambiare i criteri di esecuzione della macchina.

L'installazione delle librerie dura qualche minuto e stampa molte righe. Alla
fine deve dire `Successfully installed` seguito da un elenco.

Verifica:

```powershell
python -c "import fastapi, sqlalchemy, psycopg, argon2, pypdf; print('ok')"
```

Deve stampare `ok`.

> **Server senza internet.** Su una macchina che ha internet e la stessa
> versione di Python si scaricano prima i pacchetti:
> `pip download -r requirements.txt -d pacchetti`
> Si porta la cartella `pacchetti` sul server e si installa da li':
> `pip install --no-index --find-links=pacchetti -r requirements.txt`

### 4.4 Il file di configurazione

```powershell
Copy-Item .env.example .env
notepad .env
```

Le righe da cambiare sono **otto**. Tutte le altre restano come sono: hanno
sopra il commento che spiega a che cosa servono.

| Riga | Che cosa scriverci |
|---|---|
| `DATABASE_URL` | la si compila alla sezione 5, quando la password esiste |
| `STORAGE_PATH` | `D:\Aurora\storage` |
| `SECRET_KEY` | una stringa casuale lunga: vedi qui sotto |
| `COOKIE_SECURE` | `true` — ma **solo dopo** aver messo il certificato (sezione 6) |
| `BACKUP_PATH` | `E:\AuroraCopie` |
| `POSTGRES_BIN_PATH` | `C:\Program Files\PostgreSQL\18\bin` |
| `SERVER_PORT` | `8000`, o la porta che l'ufficio informatico ha aperto |
| `MAIL_PROVIDER` | `locale` per adesso; diventa `graph` quando la casella e' pronta |

La chiave di firma si genera cosi', e si incolla dentro `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **`COOKIE_SECURE=true` senza certificato butta fuori tutti.** Il browser non
> rimanda mai un cookie Secure su una connessione in chiaro: il modulo di
> accesso accetta la password e rimanda al modulo di accesso, all'infinito. Se
> il certificato non e' ancora arrivato si lascia `false`, si finisce
> l'installazione, e lo si accende alla sezione 6. La pagina di diagnostica lo
> ricordera' in rosso finche' non e' fatto.

---

## 5. Il database di Aurora

La procedura e' quella di `scripts/setup_postgres.md`, **parte B**. Qui c'e' il
riassunto con le due differenze della produzione.

### 5.1 Creare l'utente e il database

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

Dentro `psql`, una istruzione per volta, punto e virgola compreso:

```sql
CREATE ROLE aurora_app WITH LOGIN PASSWORD 'QUI-UNA-PASSWORD-LUNGA';
CREATE DATABASE aurora OWNER aurora_app;
GRANT ALL PRIVILEGES ON DATABASE aurora TO aurora_app;
\c aurora
GRANT ALL ON SCHEMA public TO aurora_app;
\q
```

**La password di `aurora_app` non e' quella di `postgres`** e non deve
esserlo: se un giorno le credenziali di Aurora finissero nelle mani sbagliate,
il danno deve restare dentro un database solo.

Si genera come la chiave di firma:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### 5.2 Scriverla nel file .env

```
DATABASE_URL=postgresql+psycopg://aurora_app:LA-PASSWORD@localhost:5432/aurora
```

> **Se la password contiene `@ : / # ?`** vanno codificati in percentuale:
> `@` diventa `%40`, `#` diventa `%23`, `/` diventa `%2F`. E' la ragione per
> cui conviene generarla con il comando qui sopra, che non li produce.

### 5.3 Creare le tabelle

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
alembic upgrade head
```

Verifica:

```powershell
alembic current
```

Deve rispondere con un identificativo seguito da `(head)`. Se risponde con una
riga vuota, le migrazioni non sono passate e non si va avanti.

---

## 6. Il certificato e l'https

> **Perche' non si salta questo passo.** Senza https, la password che ogni
> persona scrive nel modulo di accesso attraversa la rete aziendale **in
> chiaro**, e con lei il gettone della sessione. Chiunque abbia accesso a uno
> switch li puo' leggere e riusare. Non e' un rischio teorico ed e' il difetto
> piu' comune dei gestionali interni.

### 6.1 Convertire il certificato

L'ufficio informatico consegna di solito un file `.pfx`. Aurora vuole due file
separati in formato PEM. La conversione si fa una volta sola, con `openssl`
(che PostgreSQL si porta gia' dietro):

```powershell
$openssl = "C:\Program Files\PostgreSQL\18\bin\openssl.exe"
New-Item -ItemType Directory -Force C:\Aurora\certificati

& $openssl pkcs12 -in C:\percorso\aurora.pfx -clcerts -nokeys `
    -out C:\Aurora\certificati\aurora.crt

& $openssl pkcs12 -in C:\percorso\aurora.pfx -nocerts -nodes `
    -out C:\Aurora\certificati\aurora.key
```

Tutti e due i comandi chiedono la password del `.pfx`.

### 6.2 Proteggere la chiave privata

La chiave e' il segreto: chi la copia puo' fingersi il server. Va letta solo
dall'utente con cui gira il servizio:

```powershell
icacls C:\Aurora\certificati\aurora.key /inheritance:r
icacls C:\Aurora\certificati\aurora.key /grant "SYSTEM:(R)"
icacls C:\Aurora\certificati\aurora.key /grant "Administrators:(R)"
```

### 6.3 Scriverlo nel file .env

```
HTTPS_CERT_FILE=C:\Aurora\certificati\aurora.crt
HTTPS_KEY_FILE=C:\Aurora\certificati\aurora.key
COOKIE_SECURE=true
```

**I tre parametri si accendono insieme.** Il certificato dice come parla il
server, `COOKIE_SECURE` dice al browser di non rimandare mai il cookie in
chiaro. Uno senza l'altro e' un guasto:

| Certificato | `COOKIE_SECURE` | Che cosa succede |
|---|---|---|
| si | **si** | e' la configurazione giusta |
| si | no | la connessione e' cifrata, ma la sessione viaggia anche in chiaro |
| no | si | **nessuno riesce piu' a entrare** |
| no | no | tutto in chiaro: va bene solo in sviluppo |

La pagina `/diagnostica` guarda proprio questa coppia e ha una riga apposta,
«Connessione cifrata». Alla sezione 12 si controlla che sia verde.

### 6.4 Verifica

```powershell
python scripts\avvia.py
```

La prima riga deve dire `indirizzo: https://NOMESERVER:8000/`. Se dice
`ERRORE: il certificato indicato nel file .env non esiste`, il percorso e'
sbagliato. Si ferma con Ctrl+C.

> **Se il certificato non e' ancora arrivato**, si lasciano vuoti i due
> percorsi e `COOKIE_SECURE=false`, si finisce l'installazione e si torna qui
> il giorno in cui arriva. Sono cinque minuti e un riavvio del servizio.

---

## 7. Prima accensione, a mano

Prima di installare il servizio, Aurora si accende una volta a mano: cosi' gli
errori si leggono a schermo invece di doverli cercare in un file.

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
python scripts\avvia.py
```

Deve stampare le righe dell'indirizzo e poi restare in ascolto.

Da un **altro** PowerShell, sulla stessa macchina:

```powershell
Invoke-RestMethod http://localhost:8000/salute | ConvertTo-Json -Depth 3
```

(con https, si aggiunge `-SkipCertificateCheck` finche' il certificato non e'
riconosciuto da questa macchina)

Deve rispondere un JSON con dentro `"stato": "ok"`. Il campo `semaforo` sara'
`rosso`: e' giusto, non c'e' ancora nessuna copia di sicurezza e non c'e'
ancora nessun utente.

Si ferma il server con **Ctrl+C**.

---

## 8. La configurazione guidata

Aurora si configura da sola, dal browser, senza toccare altri file.

1. riaccendere il server (`python scripts\avvia.py`);
2. da un browser **sul server**, aprire <http://localhost:8000/>;
3. Aurora si accorge che il database e' vuoto e porta a `/primo-avvio`.

Sono sei passi, ciascuno con la sua spiegazione e un pulsante «Verifica» che
prova senza cambiare niente:

| Passo | Che cosa fa |
|---|---|
| Database | controlla che le tabelle ci siano |
| Prima persona | crea il profilo di chi amministrera' Aurora, che entra subito |
| Archivio | **scrive davvero** un file nella cartella indicata, per essere certi che si possa |
| Classificazioni | crea le classi dei documenti e la griglia dei permessi |
| Fasi | crea il percorso di fasi di partenza |
| Posta | rimandabile: si fa quando la casella e' pronta |

> **La procedura si interrompe e si riprende.** Chiudere il browser e tornare
> domani non perde niente: lo stato si ricava dal database ogni volta.

**Il profilo del primo passo e' un profilo vero**, con una password scelta
adesso: va scritta nel gestore delle password dell'azienda. E' l'unico modo di
entrare in Aurora finche' non si creano gli altri utenti.

### 8.1 Verifica

Da `/diagnostica`, la riga «Quanto c'e' dentro Aurora» deve dire almeno una
persona attiva, e la riga «Registro delle operazioni» deve avere qualche voce.

---

## 9. Il servizio di Windows

Aurora deve ripartire da sola quando il server si riavvia, e riaccendersi se
si spegne per un guasto. Su Windows serve un programma che faccia da
involucro: si usa **NSSM**.

> **Perche' non l'Utilita' di pianificazione.** Con un'operazione pianificata
> «all'avvio del sistema» Aurora ripartirebbe al riavvio, ma non si
> riaccenderebbe se il processo morisse a meta' giornata, e non comparirebbe
> in Servizi di Windows - che e' il primo posto in cui va a guardare chi non
> conosce il programma. NSSM da' tutte e due le cose e non chiede niente in
> cambio. La strada alternativa, per una macchina in cui non si possa
> installare NSSM, e' alla fine di questa sezione.

### 9.1 Installare NSSM

Si scarica da <https://nssm.cc/download> (un archivio zip, nessun
installatore). Si estrae `win64\nssm.exe` in `C:\Aurora\strumenti\nssm.exe`.

**Va scaricato da un'altra macchina se il server e' isolato**: e' un file solo.

### 9.2 Creare il servizio

Da un PowerShell **come amministratore**:

```powershell
$nssm = "C:\Aurora\strumenti\nssm.exe"

& $nssm install Aurora "C:\Aurora\.venv\Scripts\python.exe" "C:\Aurora\scripts\avvia.py"
& $nssm set Aurora AppDirectory C:\Aurora
& $nssm set Aurora DisplayName "Aurora - gestione documentazione tecnica"
& $nssm set Aurora Description "Gestionale interno dei progetti e della documentazione tecnica. Registro: C:\Aurora\logs\aurora.log"
& $nssm set Aurora Start SERVICE_AUTO_START
```

**Perche' riparta da sola** dopo un guasto:

```powershell
& $nssm set Aurora AppExit Default Restart
& $nssm set Aurora AppRestartDelay 5000
& $nssm set Aurora AppThrottle 10000
```

- `AppExit Default Restart` — comunque finisca il processo, si riaccende;
- `AppRestartDelay 5000` — aspetta cinque secondi prima di riprovare;
- `AppThrottle 10000` — se muore entro dieci secondi dall'avvio, NSSM smette
  di insistere. **E' la riga che evita il ciclo infinito** di un server che
  non riesce a partire perche' la configurazione e' sbagliata: senza,
  riproverebbe per sempre riempiendo il registro di Windows.

**Perche' aspetti PostgreSQL**, che al riavvio del server parte insieme a lei:

```powershell
& $nssm set Aurora DependOnService postgresql-x64-18
```

(il nome e' quello annotato alla sezione 2.1)

**Dove finisce quello che il programma stampa a schermo:**

```powershell
& $nssm set Aurora AppStdout C:\Aurora\logs\servizio.log
& $nssm set Aurora AppStderr C:\Aurora\logs\servizio.log
& $nssm set Aurora AppRotateFiles 1
& $nssm set Aurora AppRotateBytes 5242880
```

`servizio.log` contiene le righe dell'avvio e i guasti che avvengono **prima**
che il registro di Aurora sia pronto. Il registro vero e proprio resta
`logs\aurora.log`.

### 9.3 Con quale utente gira

Di partenza il servizio gira come `LocalSystem`, che sulla macchina puo'
tutto. **Va bene se l'archivio e le copie sono su dischi locali**; non basta
se le copie vanno su una condivisione di rete, perche' `LocalSystem` sulla
rete si presenta come il computer e non come un utente.

Con le copie su una condivisione, si chiede all'ufficio informatico un utente
di dominio dedicato (per esempio `AZIENDA\srv-aurora`) e si scrive:

```powershell
& $nssm set Aurora ObjectName "AZIENDA\srv-aurora" "la-sua-password"
```

Quell'utente deve poter **leggere e scrivere** in `C:\Aurora`,
`D:\Aurora\storage` e nella destinazione delle copie:

```powershell
icacls C:\Aurora /grant "AZIENDA\srv-aurora:(OI)(CI)M" /T
icacls D:\Aurora\storage /grant "AZIENDA\srv-aurora:(OI)(CI)M" /T
```

### 9.4 Avviare

```powershell
Start-Service Aurora
Get-Service Aurora
```

Deve rispondere `Running`.

### 9.5 Verifica: **riavviare il server**

E' la verifica che conta, e non si salta.

```powershell
Restart-Computer
```

Dopo il riavvio, senza fare login sul server, da un altro computer:

```powershell
Invoke-RestMethod https://NOMESERVER:8000/salute
```

Deve rispondere. Se risponde, Aurora riparte da sola e il criterio di
accettazione della sessione 13 e' soddisfatto.

Se non risponde:

```powershell
Get-Service Aurora
Get-Content C:\Aurora\logs\servizio.log -Tail 30
```

Le prime trenta righe di quel file dicono quasi sempre di che si tratta.

### 9.6 Senza NSSM

Se sulla macchina non si puo' installare NSSM, l'Utilita' di pianificazione
fa la meta' del lavoro:

- **Operazione nuova** → Attiva con privilegi piu' elevati, Configura per
  Windows Server;
- **Attivazione**: «All'avvio del computer», con un ritardo di **1 minuto**
  (serve a lasciar partire PostgreSQL);
- **Azione**: `C:\Aurora\.venv\Scripts\python.exe`, argomenti
  `C:\Aurora\scripts\avvia.py`, «Inizia da» `C:\Aurora`;
- **Impostazioni**: «Se l'attivita' non riesce, riavvia ogni 1 minuto», fino a
  3 volte; togliere la spunta a «Termina l'attivita' se e' in esecuzione da
  piu' di 3 giorni», che altrimenti spegne Aurora ogni tre giorni.

Quello che si perde: Aurora non compare in Servizi di Windows, e chi la deve
riavviare va cercata nell'Utilita' di pianificazione. **Va scritto nel manuale
operativo**, altrimenti il primo che ci mette le mani non la trova.

---

## 10. L'irrobustimento del registro

Il registro delle operazioni deve essere **a sola aggiunta**: si scrive e non
si tocca piu'. Non e' una buona intenzione, e' un permesso del database.

La procedura completa e' in `scripts/hardening_db.md`. Va eseguita **adesso**,
dopo `alembic upgrade head` e prima che il sistema entri in uso.

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -d aurora -f C:\Aurora\scripts\hardening_db.sql
```

Chiede la password di `postgres`.

### 10.1 Verifica

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U aurora_app -h localhost -d aurora -c "UPDATE audit_logs SET description = 'prova' WHERE false;"
```

**Deve fallire** con un errore di permessi. Se riesce, l'irrobustimento non e'
stato applicato e il registro non e' difendibile in sede di verifica.

> **Da qui in avanti, le migrazioni che toccano `audit_logs` vanno eseguite
> come `postgres`.** E' scritto in `scripts/hardening_db.md` ed e' ripetuto in
> `docs/AGGIORNAMENTO.md`, che e' il posto in cui serve saperlo.

---

## 11. La copia notturna

La procedura completa e' in `docs/BACKUP_E_RIPRISTINO.md`, sezione 5. In
breve:

1. correggere il percorso dentro `scripts\copia_notturna.cmd` se Aurora non
   sta in `C:\Aurora` (e' l'unica riga da cambiare);
2. eseguire una copia a mano, per vedere che funzioni:

   ```powershell
   cd C:\Aurora
   .\.venv\Scripts\activate
   python scripts\backup.py
   ```

3. programmarla con l'Utilita' di pianificazione, seguendo la sezione 5.2 di
   quel documento: ci sono le tre righe che di solito si sbagliano.

### 11.1 Verifica

Da `/diagnostica`, la riga «Copia di sicurezza» deve essere **verde** e dire
quando e' stata fatta.

> **La prova che conta di piu' e' un'altra, e va fatta prima della consegna:**
> ripristinare quella copia su una macchina diversa e vedere che Aurora si
> apra. La procedura passo per passo e' in `docs/BACKUP_E_RIPRISTINO.md`,
> sezione 7. Una copia di sicurezza che non e' mai stata ripristinata non e'
> una copia di sicurezza, e' una speranza.

---

## 12. Le verifiche finali

Sono nove. Si fanno tutte, nell'ordine, e si annota l'esito.

| # | Che cosa | Come | Risposta attesa |
|---|---|---|---|
| 1 | Il servizio e' avviato | `Get-Service Aurora` | `Running` |
| 2 | Riparte da sola | `Restart-Computer`, poi aprire Aurora | si apre |
| 3 | Si apre dagli altri computer | da un PC dell'ufficio, `https://NOMESERVER:8000/` | il modulo di accesso |
| 4 | Il certificato e' riconosciuto | il browser non mostra avvisi | nessun avviso |
| 5 | La diagnostica e' verde | `/diagnostica` | tutte le righe verdi |
| 6 | I cookie sono protetti | `/diagnostica`, riga «Connessione cifrata» | **verde** |
| 7 | Il registro e' a sola aggiunta | sezione 10.1 | l'`UPDATE` fallisce |
| 8 | La copia notturna e' programmata | `/diagnostica`, riga «Copia di sicurezza» | verde |
| 9 | Nessun profilo di prova | `/utenti` | nessun `prova.*` attivo |

### La verifica 9, per esteso

Sul database di sviluppo esistono profili nati durante le prove delle sessioni
precedenti: `prova.sessione5`, `piero.bertoli`, e i profili `prova.*` dei
lotti di `scripts/dati_prova.py`. **Su un'installazione nuova non ci sono**,
perche' il database e' vuoto e la configurazione guidata crea solo il primo
profilo.

Se l'installazione e' partita da una copia del database di sviluppo - cosa
che si dovrebbe evitare, ma capita - quei profili vanno **disattivati** da
`/utenti` uno per uno. Non si cancellano: le loro operazioni sono nel
registro, e un profilo cancellato renderebbe illeggibili quelle righe
(regola 5 di CLAUDE.md).

Da controllare anche l'utente `admin` di `scripts/seed.py`: se e' stato usato
per installare, la sua password va cambiata; se non serve, si disattiva.

---

## 13. L'ambiente di prova sulla stessa macchina

Serve a due cose che senza di lui si fanno in produzione: provare
l'aggiornamento **prima** di installarlo, e mostrare Aurora a chi la deve
imparare senza che scriva dentro i dati veri.

**Deve essere separato in tutto e per tre cose in particolare**: database,
archivio, copie. Un ambiente di prova che condivide anche solo una delle tre
con la produzione non e' un ambiente di prova: e' un secondo modo di scrivere
nei dati veri.

| | Produzione | Prova |
|---|---|---|
| Cartella | `C:\Aurora` | `C:\AuroraProva` |
| Database | `aurora` | `aurora_prova` |
| Utente PostgreSQL | `aurora_app` | `aurora_prova` |
| Archivio | `D:\Aurora\storage` | `D:\AuroraProva\storage` |
| Copie | `E:\AuroraCopie` | **nessuna** |
| Porta | 8000 | **8001** |
| Servizio | `Aurora` | `AuroraProva` |

### 13.1 Il database di prova

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

```sql
CREATE ROLE aurora_prova WITH LOGIN PASSWORD 'una-password-diversa';
CREATE DATABASE aurora_prova OWNER aurora_prova;
\c aurora_prova
GRANT ALL ON SCHEMA public TO aurora_prova;
\q
```

> **L'utente di Aurora non puo' creare database**, ed e' giusto cosi': e'
> un'operazione da amministratore. Questo passo lo esegue chi ha la password
> di `postgres`.

### 13.2 Il programma

```powershell
Copy-Item -Recurse C:\Aurora C:\AuroraProva -Exclude .venv,logs,storage,backup
cd C:\AuroraProva
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
alembic upgrade head
```

Nel `.env` di `C:\AuroraProva` si cambiano **cinque righe**, e sono le cinque
che tengono separati i due ambienti:

```
DATABASE_URL=postgresql+psycopg://aurora_prova:la-password@localhost:5432/aurora_prova
STORAGE_PATH=D:\AuroraProva\storage
BACKUP_PATH=D:\AuroraProva\copie-non-usate
SERVER_PORT=8001
APP_NAME=Aurora (PROVA)
```

**`APP_NAME` non e' un dettaglio.** Compare nel titolo della finestra e nella
barra laterale di ogni pagina: e' l'unica cosa che impedisce a qualcuno di
lavorare per mezz'ora sull'ambiente sbagliato. Va scritto in modo che si veda.

### 13.3 Il servizio di prova

```powershell
$nssm = "C:\Aurora\strumenti\nssm.exe"
& $nssm install AuroraProva "C:\AuroraProva\.venv\Scripts\python.exe" "C:\AuroraProva\scripts\avvia.py"
& $nssm set AuroraProva AppDirectory C:\AuroraProva
& $nssm set AuroraProva DisplayName "Aurora PROVA - non e' il sistema vero"
& $nssm set AuroraProva Start SERVICE_DEMAND_START
```

`SERVICE_DEMAND_START` e non `AUTO`: l'ambiente di prova si accende quando
serve e resta spento il resto del tempo. Un secondo Aurora acceso per sempre
e' un secondo Aurora che qualcuno prima o poi apre per sbaglio.

```powershell
Start-Service AuroraProva
```

### 13.4 Riempirlo di dati

Con un database vuoto, l'ambiente di prova si configura da `/primo-avvio` come
la produzione. Per avere qualcosa dentro su cui provare davvero:

```powershell
cd C:\AuroraProva
.\.venv\Scripts\activate
python scripts\seed.py
python scripts\dati_prova.py
```

`dati_prova.py` scrive 15 persone, 20 prodotti, 300 documenti e 500 messaggi
finti. **Chiede conferma e dice in quale database sta per scrivere**: e' il
momento in cui ci si accorge di averlo lanciato dalla cartella sbagliata.

> **Non si copiano i dati di produzione nell'ambiente di prova.** Ci sono
> dentro la corrispondenza con i clienti e i documenti riservati, e
> l'ambiente di prova ha meno protezioni per definizione. Se serve un caso
> vero per riprodurre un difetto, si copia **quel** caso, non tutto.

### 13.5 Verifica

Da un browser: `http://localhost:8001/`. La barra laterale deve dire
**«Aurora (PROVA)»**. Se dice «Aurora», il `.env` sbagliato e' quello aperto:
si controlla in quale cartella si e' scritto.

---

## 14. Che cosa consegnare a chi amministrera'

1. **`docs/MANUALE_OPERATIVO.md`**, che e' scritto per lui: come si avvia e si
   ferma, dove sono i registri, i cinque problemi piu' probabili;
2. **le credenziali**, nel gestore delle password dell'azienda e non altrove:
   la password di `postgres`, quella di `aurora_app`, quella del primo profilo
   di Aurora, e - se c'e' - quella dell'utente di servizio;
3. **il foglio con i percorsi di questa installazione**: si stampa
   direttamente dalla pagina `/diagnostica`, che li elenca in fondo;
4. **`docs/AGGIORNAMENTO.md`**, per il giorno in cui arrivera' una versione
   nuova;
5. **`docs/BACKUP_E_RIPRISTINO.md`**, e soprattutto **la data dell'ultima
   prova di ripristino riuscita**. Se non ce n'e' una, la consegna non e'
   finita.

---

## Appendice — Problemi frequenti durante l'installazione

| Sintomo | Causa quasi sempre | Rimedio |
|---|---|---|
| `python` non e' riconosciuto | PATH non sistemato, oppure PowerShell aperto prima dell'installazione | riaprire PowerShell; se non basta, «Modify» sull'installatore di Python |
| `Activate.ps1 non puo' essere caricato` | criteri di esecuzione di PowerShell | usare `activate.bat` |
| `alembic upgrade head` dice «connection refused» | PostgreSQL non e' avviato | `Start-Service postgresql-x64-18` |
| `alembic upgrade head` dice «password authentication failed» | `DATABASE_URL` non torna con la password di `aurora_app` | ricontrollare la riga; attenzione ai caratteri da codificare |
| Il servizio parte e si ferma subito | quasi sempre configurazione | `Get-Content C:\Aurora\logs\servizio.log -Tail 30` |
| Aurora si apre sul server e non dagli altri computer | firewall, oppure `SERVER_HOST=127.0.0.1` | verificare la regola del firewall e la riga nel `.env` |
| Il browser dice che il certificato non e' attendibile | l'autorita' interna non e' distribuita su quel computer | e' una richiesta all'ufficio informatico, non un problema di Aurora |
| Si accede e si torna sempre al modulo di accesso | `COOKIE_SECURE=true` senza https davanti | mettere il certificato, oppure `COOKIE_SECURE=false` finche' non arriva |
| Il caricamento dei documenti e' lentissimo | antivirus sulla cartella dell'archivio | richiesta 1 della sezione 3 |
| «Il file non e' leggibile dall'archivio» | `STORAGE_PATH` punta alla cartella sbagliata, o il disco non e' collegato | `/diagnostica`, riga «Integrita' dell'archivio» |
