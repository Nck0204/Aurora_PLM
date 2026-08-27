# Copia di sicurezza e ripristino di Aurora

Questo documento e' scritto per un informatico che **non conosce Aurora**. Non
serve aver letto nient'altro del progetto: qui c'e' che cosa va copiato, come si
programma la copia notturna, e come si rimette in piedi il sistema quando serve.

Va tenuto stampato accanto al server, o comunque **fuori** dal server. Il
giorno in cui serve, il server potrebbe non accendersi.

---

## 0. In due minuti

| Cosa | Comando |
|---|---|
| Fare una copia adesso | `python scripts/backup.py` |
| Vedere le copie disponibili | `python scripts/ripristino.py --elenca` |
| Ripristinare l'ultima copia | `python scripts/ripristino.py` |
| Controllare che i file ci siano tutti | `python scripts/ripristino.py --solo-verifica` |
| Vedere se la copia notturna gira | aprire `/diagnostica` nel programma |

Tutti i comandi si danno dalla cartella di Aurora, con l'ambiente virtuale
attivo:

```
cd C:\Aurora
.venv\Scripts\activate
```

---

## 1. Che cosa va copiato, e perche' sono due cose

I dati di Aurora stanno in **due posti diversi**. Copiarne uno solo non serve a
niente, ed e' l'errore piu' facile da fare.

**Il database PostgreSQL.** Contiene chi ha caricato che cosa, quando, con
quale revisione, chi lo puo' vedere, e tutto il registro delle operazioni. Non
contiene i file.

**L'archivio dei file**, cioe' la cartella indicata dal parametro
`STORAGE_PATH` nel file `.env`. Contiene il contenuto vero dei documenti, degli
allegati e dei messaggi di posta. I file ci stanno con un nome che e' una
sequenza di 64 caratteri esadecimali, e non con il loro nome originale.

> Un database senza archivio e' un elenco di documenti che non si scaricano. Un
> archivio senza database e' una cartella piena di file dal nome incomprensibile.

Lo script `scripts/backup.py` copia tutti e due.

### Che cosa non viene copiato, e perche'

| Non copiato | Perche' |
|---|---|
| `storage/tmp/` | caricamenti interrotti: non li riferisce nessuna riga del database |
| `storage/posta/` | messaggi in transito. Quello che conta di loro e' gia' dentro `objects/` |
| `storage/posta_graph.json` | e' un segnalibro, si ricostruisce da solo |
| `logs/` | serve a indagare su un guasto, non a ripristinare, e ruota da solo |

### Che cosa **e'** dentro la copia, ed e' delicato

Dentro `configurazione.env` c'e' la password del database e il segreto con cui
Aurora legge la casella aziendale. Dentro `database.dump` ci sono tutte le
impronte delle password e tutto il registro delle operazioni.

**La cartella delle copie va protetta come il server.** Se e' su una
condivisione di rete, i permessi vanno dati solo all'utente con cui gira il
lavoro pianificato.

---

## 2. Com'e' fatta una copia

```
D:\CopieAurora\
├── archivio\                    i file, copiati una volta sola per sempre
│   └── 3f\9a\3f9a2c11...
├── aurora-2026-08-27_0300\
│   ├── database.dump            il salvataggio di PostgreSQL
│   ├── configurazione.env       copia del file .env di quel giorno
│   └── informazioni.json        versione, data, conteggi, migrazione
├── aurora-2026-08-26_0300\
└── aurora-2026-08-25_0300\
```

**L'archivio e' uno solo e cresce; i salvataggi del database sono tanti e
ruotano.** Non e' una scorciatoia per risparmiare spazio.

Un file dell'archivio ha per nome l'impronta SHA-256 del proprio contenuto,
quindi non cambia mai - se il contenuto cambiasse, cambierebbe anche il nome, e
sarebbe un altro file - e Aurora non ne cancella mai nessuno. Ne discende la
proprieta' che rende sensata tutta la procedura: **la cartella `archivio/` e' un
soprainsieme dell'archivio a qualunque data passata.**

Ripristinando il database di martedi' insieme all'archivio di oggi si ottiene un
sistema coerente: tutte le impronte che il database di martedi' nomina sono li'
dentro, piu' qualcuna in piu' che nessuno riferisce e che non fa male a nessuno.

Copiare l'archivio per intero ogni notte, invece, vorrebbe dire riscrivere
decine di gigabyte per aggiungere i tre file caricati ieri.

**Una copia e' completa quando c'e' `informazioni.json`.** Quel file viene
scritto per ultimo: una cartella senza di lui e' una copia interrotta a meta',
e sia la rotazione sia il ripristino la riconoscono per tale e la ignorano.

---

## 3. La configurazione

Nel file `.env` di Aurora servono tre parametri. Se non ci sono, si aggiungono
in fondo.

```
# Dove finiscono le copie. SU UN DISCO DIVERSO da quello di Aurora.
BACKUP_PATH=D:\CopieAurora

# Quante copie del database si conservano. L'archivio dei file non ruota mai.
BACKUP_KEEP=7

# La cartella "bin" di PostgreSQL: quella con pg_dump.exe e pg_restore.exe.
# Vuota = si cercano nel PATH di sistema.
POSTGRES_BIN_PATH=C:\Program Files\PostgreSQL\18\bin
```

**Su un disco diverso.** Una copia sullo stesso disco protegge dallo sbaglio di
una persona e da nient'altro, e il guasto che si teme di piu' e' proprio quello
del disco. Meglio ancora su una condivisione di rete o su un disco esterno che
qualcuno stacca.

### Verifica che pg_dump si trovi

```
python scripts/backup.py --solo-database
```

Se risponde `pg_dump non e' stato trovato`, il parametro `POSTGRES_BIN_PATH`
non e' giusto. La cartella si trova cosi':

```powershell
Get-ChildItem "C:\Program Files\PostgreSQL" -Directory
```

---

## 4. La prima copia, a mano

```
cd C:\Aurora
.venv\Scripts\activate
python scripts\backup.py
```

Deve stampare qualcosa del genere:

```
Copia di sicurezza di Aurora - 27/08/2026 14:12
==============================================================
  Destinazione: D:\CopieAurora
  Salvataggio di aurora_app@localhost:5432/aurora ...
  Salvataggio verificato: 164 oggetti dentro.
  Archivio: 3745 file copiati, 0 gia' presenti.

  Copia completata in 7 secondi: database 99,7 KB, archivio 3745 file
  nuovi su 3745.
```

La riga **"Salvataggio verificato"** e' quella che conta: vuol dire che il file
prodotto e' stato riletto e che si riesce a leggerne l'indice. Un file troncato
- disco pieno, processo interrotto - esiste e non e' vuoto, e senza questa
verifica ci si accorgerebbe che non vale il giorno in cui serve.

Eseguendo lo script una seconda volta, l'archivio dira' `0 file copiati, 3745
gia' presenti`: e' la copia incrementale che funziona.

### Codici di uscita

| Codice | Significato |
|---|---|
| 0 | la copia e' riuscita |
| 1 | la copia non e' riuscita, o e' riuscita a meta' |
| 2 | la copia non e' potuta partire (pg_dump assente, disco scollegato) |

E' quello che l'Utilita' di pianificazione guarda per sapere com'e' andata.

---

## 5. Programmare la copia notturna con l'Utilita' di pianificazione

### 5.1 Il file di comando

Nel progetto c'e' gia': **`scripts\copia_notturna.cmd`**. Va aperto e
corretto in un punto solo, la riga `cd /d C:\Aurora`, se Aurora non sta li'.
Dentro c'e' questo:

```
@echo off
cd /d C:\Aurora
call .venv\Scripts\activate.bat
python scripts\backup.py --silenzioso
exit /b %ERRORLEVEL%
```

L'ultima riga non e' un dettaglio: **restituisce all'Utilita' di
pianificazione il codice di uscita dello script**, ed e' l'unica cosa che le
permette di sapere che la copia e' fallita. Senza, ogni notte risulterebbe
riuscita.

`--silenzioso` fa stampare qualcosa solo in caso di guasto: un'operazione che
scrive mezza pagina ogni notte e' un'operazione che dopo un mese nessuno legge
piu'. I guasti vanno comunque sull'uscita degli errori e si vedono.

### 5.2 L'operazione pianificata

Aprire l'**Utilita' di pianificazione** (`taskschd.msc`) e scegliere **«Crea
attivita»**, non «Crea attivita di base»: quella di base non permette di
scegliere l'utente con cui l'operazione gira, e qui l'utente conta.

**Scheda «Generale»**

| Campo | Valore |
|---|---|
| Nome | `Aurora - copia di sicurezza` |
| Descrizione | `Copia notturna del database e dell'archivio dei file.` |
| Utente | l'utente **con cui gira Aurora**, non l'amministratore |
| | Selezionare **«Esegui indipendentemente dalla connessione dell'utente»** |
| | Selezionare **«Esegui con i privilegi piu' elevati»** solo se il disco di destinazione lo richiede |
| Configura per | Windows Server della versione in uso |

> **L'utente conta.** Deve poter leggere l'archivio di Aurora e scrivere sulla
> destinazione. Se la destinazione e' una condivisione di rete, un account di
> sistema (`SYSTEM`) **non** la vede: serve un utente di dominio.

**Scheda «Attivazione»** — Nuovo:

| Campo | Valore |
|---|---|
| Avvia l'attivita' | In base a una pianificazione |
| | Giornaliera, ore **03:00** |
| Ripeti l'attivita' ogni | (lasciare deselezionato) |
| Attivato | si' |

Le tre di notte e non a mezzanotte: a mezzanotte partono anche gli altri lavori
pianificati del server, e due lavori che leggono lo stesso disco insieme
durano il doppio.

**Scheda «Azioni»** — Nuovo:

| Campo | Valore |
|---|---|
| Azione | Avvio programma |
| Programma o script | `C:\Aurora\scripts\copia_notturna.cmd` |
| Argomenti | (vuoto) |
| Inizia da | `C:\Aurora` |

Il campo **«Inizia da»** va compilato. Senza, lo script parte dalla cartella
di sistema e non trova il file `.env`.

**Scheda «Condizioni»**

| Campo | Valore |
|---|---|
| Avvia solo se il computer e' alimentato | **deselezionare** (e' un server) |
| Riattiva il computer per eseguire | deselezionare |
| Avvia solo se e' disponibile la connessione di rete | selezionare **solo** se la destinazione e' in rete |

**Scheda «Impostazioni»**

| Campo | Valore |
|---|---|
| Consenti l'esecuzione su richiesta | si' |
| Esegui il prima possibile dopo un avvio pianificato non eseguito | **si'** |
| Se l'attivita' non riesce, riavvia ogni | 30 minuti, fino a 3 volte |
| Interrompi l'attivita' se e' in esecuzione da piu' di | 4 ore |
| Se l'attivita' e' gia' in esecuzione | Non avviare una nuova istanza |

La riga **«Esegui il prima possibile dopo un avvio pianificato non eseguito»**
e' quella che copre il caso del server spento di notte: al riavvio la copia
parte comunque.

### 5.3 Provarla subito

Nell'elenco delle operazioni, tasto destro sull'attivita' e **«Esegui»**. Dopo
qualche secondo la colonna **«Risultato ultima esecuzione»** deve dire
`L'operazione e' stata completata (0x0)`.

| Risultato | Che cosa vuol dire |
|---|---|
| `0x0` | la copia e' riuscita |
| `0x1` | la copia e' fallita: vedere `/diagnostica` nel programma |
| `0x2` | non e' partita: `pg_dump` non trovato, o disco assente |
| `0x1` subito, senza aver fatto niente | il file `.cmd` non e' stato trovato, o «Inizia da» e' vuoto |

### 5.4 Controllare che continui a girare

Aprire **`/diagnostica`** dentro Aurora, riga **«Copia di sicurezza»**. Dice
quando e' stata l'ultima, com'e' andata e quanto ha copiato:

- **verde**: l'ultima copia e' riuscita ed e' recente;
- **giallo**: e' riuscita ma e' vecchia di piu' di trenta ore. L'operazione
  pianificata non sta girando;
- **rosso**: l'ultima e' fallita, oppure non ne e' mai stata fatta nessuna.

La stessa informazione, per un programma di sorveglianza, e' all'indirizzo
`/salute`, nel controllo chiamato `backup`.

---

## 6. Il ripristino

### 6.1 Prima di cominciare

Il ripristino **sovrascrive un database**. Prima di eseguirlo su un sistema che
contiene qualcosa, fare una copia di quello che c'e':

```
python scripts\backup.py
```

Costa qualche secondo e non si sa mai.

### 6.2 Vedere che cosa c'e' da ripristinare

```
python scripts\ripristino.py --elenca
```

```
  Copie disponibili in D:\CopieAurora:

    aurora-2026-08-27_0300   2026-08-27T03:00:11+02:00   database 99,7 KB
    aurora-2026-08-26_0300   2026-08-26T03:00:09+02:00   database 99,5 KB
```

### 6.3 Ripristinare

```
python scripts\ripristino.py
```

oppure, per una copia che non e' l'ultima:

```
python scripts\ripristino.py --copia aurora-2026-08-26_0300
```

Lo script mostra prima che cosa c'e' dentro la copia - la data, la macchina, la
versione di Aurora, quante righe c'erano - e **poi** chiede conferma. Sono due
domande:

1. scrivere **per esteso il nome del database** che si sta per sovrascrivere.
   Non "si", non "y": il nome. Chi lo scrive lo ha letto, e chi lo ha letto non
   sta ripristinando sul server sbagliato;
2. se il database di destinazione non e' vuoto, confermare quante righe si
   stanno per buttare via.

### 6.4 Che cosa fa, in ordine

1. rimette il database con `pg_restore --clean --if-exists`;
2. rimette nell'archivio i file che mancano (non sovrascrive quelli che ci sono
   gia': hanno per nome l'impronta del proprio contenuto, quindi sono gia'
   quelli giusti);
3. **verifica la coerenza**: per ogni impronta che il database nomina, controlla
   che il file esista davvero.

Il passo 3 e' quello che distingue un ripristino da una speranza di ripristino:

```
  VERIFICA DI COERENZA FRA DATABASE E ARCHIVIO
    file attesi dal database ......... 3745
    file trovati sul disco ........... 3745
    attesi e NON trovati ............. 0
    trovati e non riferiti da nessuno  0

  QUANTO C'E' DENTRO ADESSO
    Documenti attivi................... 1482
    Versioni di documento.............. 3106
    ...

  Il ripristino e' coerente: ogni file nominato dal database c'e'.
```

Se compare **"IL RIPRISTINO NON E' COMPLETO"** con dei file mancanti, quei
documenti compariranno negli elenchi e non si scaricheranno. Le due cause
possibili sono che `STORAGE_PATH` punti alla cartella sbagliata, o che nella
copia non ci fosse l'archivio.

### 6.5 Le righe di segnalazione di pg_restore sono normali

Su una macchina nuova, `pg_restore` scrive decine di righe del tipo `l'oggetto
"x" non esiste, saltato` o segnalazioni sui permessi di ruoli che li' non
esistono. Sono normali e lo script lo dice. Quello che conta e' la verifica di
coerenza in fondo.

### 6.6 Dopo il ripristino: due cose da controllare

1. **il file `.env` di questa macchina** deve puntare al database giusto e alla
   cartella dell'archivio giusta. Nella copia c'e' `configurazione.env`, che e'
   il `.env` della macchina di origine: si puo' usare come riferimento, ma se
   la macchina e' diversa i percorsi vanno corretti;
2. **l'irrobustimento del registro va rifatto** sul database ripristinato. Il
   ripristino ricrea le tabelle, e con esse spariscono i permessi e i grilletti
   che rendono `audit_logs` a sola aggiunta:

   ```
   psql -U postgres -h localhost -d aurora -f scripts\hardening_db.sql
   ```

   La procedura completa e' in `scripts/hardening_db.md`.

---

## 7. Provare il ripristino su una macchina diversa. **Prima.**

> **Una copia di sicurezza che non e' mai stata ripristinata non e' una copia
> di sicurezza: e' una speranza.**

Questa e' la raccomandazione piu' importante di tutto il documento, ed e' anche
la piu' facile da rimandare. Va fatta **prima della messa in esercizio**, su una
macchina **diversa** dal server, e ripetuta almeno una volta l'anno.

Perche' su una macchina diversa e non sullo stesso server: sullo stesso server
funziona anche un ripristino che dipende da qualcosa che c'e' solo li' - un
percorso, un ruolo del database, una variabile d'ambiente - e quel qualcosa il
giorno del guasto non ci sara'.

### La prova, passo per passo

**1. Su una macchina qualunque con PostgreSQL installato**, creare un database
vuoto:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

```sql
CREATE ROLE aurora_app WITH LOGIN PASSWORD 'una_password';
CREATE DATABASE aurora_prova OWNER aurora_app;
\q
```

**2. Copiare la cartella di Aurora** (senza `storage/` e senza `.env`) e
preparare un `.env` che punti al database di prova e a una cartella di archivio
vuota:

```
DATABASE_URL=postgresql+psycopg://aurora_app:una_password@localhost:5432/aurora_prova
STORAGE_PATH=C:\ProvaRipristino\archivio
SECRET_KEY=una-chiave-qualunque-per-la-prova
```

**3. Rendere raggiungibile la cartella delle copie** (disco esterno, condivisione
di rete, o una copia della cartella).

**4. Ripristinare:**

```
python scripts\ripristino.py --da D:\CopieAurora
```

**5. Controllare tre cose, e sono tre e non una:**

- la verifica di coerenza in fondo allo script dice **0 file mancanti**;
- i conteggi (documenti, versioni, messaggi, registro) **coincidono** con
  quelli scritti in `informazioni.json` della copia;
- si avvia Aurora (`uvicorn app.main:app`), si entra, **si apre un documento e
  lo si scarica.** Questa e' la prova che vale piu' di tutte le altre messe
  insieme: e' l'unica che percorre tutta la strada, dal database al file sul
  disco.

**6. Buttare via il database di prova** quando si e' finito:

```sql
DROP DATABASE aurora_prova;
```

### Annotare l'esito

Segnare da qualche parte - un foglio nell'armadio del server va benissimo - la
data della prova e l'esito. Serve a due cose: a sapere quando rifarla, e a poter
rispondere «si', l'abbiamo provata, il 12 marzo» quando qualcuno lo chiedera'.

---

## 8. Che cosa fare quando qualcosa va storto

| Sintomo | Causa piu' probabile | Rimedio |
|---|---|---|
| `pg_dump non e' stato trovato` | `POSTGRES_BIN_PATH` sbagliato o vuoto | scrivere la cartella `bin` di PostgreSQL nel `.env` |
| `pg_dump si e' fermato con un errore: password authentication failed` | credenziali sbagliate in `DATABASE_URL` | correggere il `.env` |
| `il file del salvataggio e' vuoto` | disco pieno | liberare spazio sulla destinazione |
| `non si riesce a leggerlo: e' troncato o rovinato` | copia interrotta, disco pieno | ripetere la copia; controllare lo spazio |
| `La cartella dell'archivio non esiste` | disco dell'archivio scollegato, o `STORAGE_PATH` sbagliato | ricollegare il disco; correggere il `.env` |
| l'operazione pianificata risulta `0x1` ogni notte | vedere `/diagnostica` nel programma: la riga della copia porta il motivo | |
| l'operazione pianificata non parte mai | utente sbagliato, o «Inizia da» vuoto | rivedere la sezione 5.2 |
| il ripristino e' finito ma dei documenti non si scaricano | l'archivio non e' stato ripristinato | `python scripts\ripristino.py --solo-verifica` per contare quanti mancano |

### La domanda che si fa piu' spesso

**«Posso copiare la cartella dell'archivio con un normale programma di backup
del server, e lasciare a questo script solo il database?»**

Si', e in un'azienda che ha gia' un sistema di copie funzionante e' spesso la
scelta giusta. In quel caso:

```
python scripts\backup.py --solo-database
```

e si include `STORAGE_PATH` nel backup aziendale. L'unica cosa da non fare e' il
contrario: copiare i file e non il database.

**«L'archivio nella cartella delle copie cresce e non si svuota mai. E'
normale?»**

Si'. Aurora non cancella mai un file dall'archivio, quindi non lo cancella
nemmeno dalla copia: un file che c'e' nella copia e non c'e' piu' nell'originale
e' precisamente quello che una copia di sicurezza serve a conservare. Se lo
spazio diventa un problema, la risposta e' un disco piu' grande - la pagina
`/diagnostica` dice fra quanti mesi finira' - non una pulizia.
