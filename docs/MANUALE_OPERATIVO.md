# Manuale operativo di Aurora

**Per chi tiene in piedi Aurora al posto di chi l'ha costruita.**

Questo documento non spiega come si usa Aurora - quello e' dentro il programma,
alla voce **Aiuto** della barra laterale. Spiega come si tiene accesa: come si
avvia e si ferma, dove sono i registri, che cosa fare quando qualcosa non va,
come si rimette in piedi dopo un guasto.

E' scritto perche' lo legga qualcuno che di Aurora **non sa niente**, magari
di sabato mattina, chiamato al telefono da un collega che dice «Aurora non
funziona». Non c'e' niente da sapere prima: i nomi delle cose sono scritti per
esteso.

---

## In una pagina

| Domanda | Risposta |
|---|---|
| Che cos'e' | il gestionale della documentazione tecnica: prodotti, progetti, documenti, posta |
| Dove gira | sul server **NOMESERVER**, in rete locale. Non usa internet |
| Come si apre | `https://NOMESERVER:8000/` da un browser dell'ufficio |
| Come si riavvia | Servizi di Windows → **Aurora** → Riavvia |
| Come si sa se sta bene | `https://NOMESERVER:8000/diagnostica` |
| Dov'e' il registro | `C:\Aurora\logs\aurora.log` sul server |
| Dove sono i dati | database PostgreSQL `aurora` + cartella `D:\Aurora\storage` |
| Dove sono le copie | `E:\AuroraCopie`, fatte ogni notte |
| Chi chiamare | vedi l'ultima sezione |

> I percorsi qui sopra sono quelli dell'installazione tipo. **Quelli veri di
> questa macchina** stanno in fondo alla pagina `/diagnostica`, che li elenca
> per esteso: quella pagina si stampa e si tiene con questo manuale.

---

## 1. Come si avvia e come si ferma

Aurora e' un **servizio di Windows**. Si chiama `Aurora` e parte da sola
quando il server si accende.

### Dalla finestra Servizi

`Win+R` → `services.msc` → cercare **Aurora** nell'elenco → tasto destro →
Avvia, Arresta o **Riavvia**.

### Da PowerShell

```powershell
Get-Service Aurora        # come sta
Restart-Service Aurora    # riavvia
Stop-Service Aurora       # ferma
Start-Service Aurora      # avvia
```

**Il riavvio dura una decina di secondi.** Chi ha una pagina aperta in quel
momento vede un errore del browser e deve ricaricare: non perde niente di
quello che aveva gia' salvato.

### Che cosa NON si ferma

**PostgreSQL** (il servizio `postgresql-x64-18`) non va fermato per riavviare
Aurora. Contiene tutti i dati: si ferma solo quando qualcuno che sa quello che
fa lo chiede espressamente.

### Riavviare Aurora e' quasi sempre innocuo

Non perde dati: tutto quello che una persona ha salvato e' gia' nel database.
Interrompe solo due cose, e nessuna delle due fa danni:

- **un caricamento in corso**: chi stava caricando lo rifa';
- **una lettura della posta in corso**: riparte al controllo successivo, e i
  messaggi non si perdono - quelli non ancora archiviati restano nella
  casella.

Se il dubbio e' «riavvio o non riavvio?», la risposta e' **riavvia**.

---

## 2. Dove sono i registri

| File | Che cosa contiene |
|---|---|
| `C:\Aurora\logs\aurora.log` | il registro di Aurora: ogni richiesta, ogni errore, ogni operazione |
| `C:\Aurora\logs\aurora.log.1` … `.10` | i precedenti. Ogni file arriva a 5 MB e poi ruota |
| `C:\Aurora\logs\servizio.log` | quello che il programma stampa **prima** di aprire il proprio registro. Si guarda quando il servizio non parte |

Le ultime cinquanta righe, che sono quelle che servono quasi sempre:

```powershell
Get-Content C:\Aurora\logs\aurora.log -Tail 50
```

Guardarlo mentre succede qualcosa (si esce con Ctrl+C):

```powershell
Get-Content C:\Aurora\logs\aurora.log -Tail 20 -Wait
```

I soli errori di oggi:

```powershell
Select-String -Path C:\Aurora\logs\aurora.log -Pattern "ERROR" |
    Select-Object -Last 30
```

### Le righe che si leggono piu' spesso

```
2026-09-01 09:14:22  ERROR  aurora  Errore non gestito [3f9a2c11] su GET /documenti
```

`[3f9a2c11]` e' il **codice di riferimento**: quando qualcuno dice «e'
comparso l'errore 3f9a2c11», quel codice si cerca in questo file e porta alla
riga con la spiegazione tecnica completa.

```
2026-09-01 09:14:20  INFO  aurora.audit  audit document.created su documents/... da utente=... ip=...
```

Sono le operazioni. **Il registro vero delle operazioni non e' questo file**:
e' dentro Aurora, alla voce **Registro** della barra laterale, ed e' quello
che si guarda per rispondere a «chi ha fatto questa cosa e quando».

### C'e' anche un registro di sicurezza

Il registro delle operazioni dentro Aurora **non si puo' modificare**: il
database non lo permette, nemmeno al programma stesso, e ogni voce porta
l'impronta della precedente. Serve a rispondere in sede di verifica aziendale.
Non c'e' niente da fare per tenerlo in piedi; per controllare che sia integro:

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
python scripts\verifica_audit.py
```

Va bene farlo una volta ogni tanto, o quando qualcuno lo chiede. Dura qualche
secondo e dice `catena integra` oppure che cosa non torna.

---

## 3. Come si legge la diagnostica

`https://NOMESERVER:8000/diagnostica` — bisogna essere entrati con un profilo
di amministratore. E' la pagina da aprire **per prima**, sempre, prima ancora
di guardare i registri.

Una riga per controllo, con un semaforo. **Le righe non verdi stanno in
cima.**

### I tre colori, e cosa vogliono dire

| Colore | Che cosa vuol dire | Che cosa si fa |
|---|---|---|
| **verde** | non c'e' niente da fare | niente |
| **giallo** | c'e' qualcosa da programmare, ma non oggi | si legge e si mette in agenda |
| **rosso** | qualcosa e' gia' rotto, e qualcuno se ne sta accorgendo | si legge il blocco «Che cosa fare» e lo si esegue |

Non esiste un quarto colore. Un controllo che **non riesce** a rispondere e'
giallo: non saperlo e' esso stesso un problema da guardare.

### La regola da cui dipende tutto il resto

**Ogni riga che non e' verde dice che cosa fare**, non che cosa e' successo.
Non «il servizio PostgreSQL non risponde», ma «apri Servizi di Windows, cerca
il servizio che comincia per postgresql e premi Avvia». Le istruzioni sono
scritte con i nomi veri delle cose: si eseguono senza sapere altro.

**Se una riga rossa non dice che cosa fare, e' un difetto del programma** e va
segnalato: c'e' un test che lo verifica, quindi non dovrebbe succedere.

### Gli undici controlli

| Riga | A che domanda risponde |
|---|---|
| Collegamento al database | PostgreSQL risponde? in quanti millisecondi? |
| Connessione cifrata | le password attraversano la rete in chiaro? |
| Copia di sicurezza | l'ultima copia: quando, com'e' andata, quanto ha copiato |
| Spazio sul disco | quanto e' libero, e **fra quanti mesi finisce** |
| Integrita' dell'archivio | i file che il database si aspetta ci sono tutti? |
| Collegamento alla casella di posta | da dove arriva la posta, e quando e' andata bene l'ultima volta |
| Messaggi in quarantena | quanti aspettano che una persona li smisti |
| Registro delle operazioni | quante voci, a quando risale l'ultima |
| Quanto c'e' dentro Aurora | documenti, versioni, messaggi, persone attive |
| Scadenza del segreto applicativo | fra quanti giorni la posta smette di arrivare |
| Errori nelle ultime 24 ore | quante righe di errore, con il dettaglio |

**«Fra quanti mesi finisce il disco» e' la riga che serve davvero.** Sapere che
restano 400 GB non dice niente; sapere che al ritmo degli ultimi trenta giorni
finiscono fra cinque mesi fa comprare il disco *prima*.

### Se il database e' spento, la pagina non si apre

E non e' una dimenticanza: per aprirla bisogna essere entrati, e per entrare
serve il database. In quel caso Aurora mostra una pagina che dice **la stessa
identica istruzione** che si leggerebbe li'. E `https://NOMESERVER:8000/salute`
risponde comunque, sempre, anche quando tutto il resto e' rotto: e' la pagina
da aprire quando non si apre niente.

---

## 4. I cinque problemi piu' probabili

Sono in ordine di probabilita'. Per ciascuno: come si riconosce, che cosa e'
successo, che cosa si fa.

---

### 4.1 «Aurora non si apre» — pagina bianca o «impossibile raggiungere il sito»

**Come si riconosce.** Il browser non arriva da nessuna parte. Succede a tutti
insieme, non a una persona sola.

**Che cosa e' successo, in ordine di probabilita'.**

1. Il servizio Aurora si e' fermato.
2. PostgreSQL si e' fermato, e Aurora e' partita e non riesce a lavorare.
3. Il server e' stato riavviato e qualcosa non e' ripartito.
4. La rete: il server e' spento o irraggiungibile.

**Che cosa si fa.**

```powershell
# 1. Aurora e' viva?
Get-Service Aurora

# Se dice Stopped:
Start-Service Aurora
# e poi si va a leggere perche' si era fermata:
Get-Content C:\Aurora\logs\servizio.log -Tail 30

# 2. Se dice Running ma le pagine non si aprono, si guarda dal server stesso:
Invoke-RestMethod http://localhost:8000/salute

# Se risponde: Aurora sta bene, il problema e' la rete o il firewall.
# Se non risponde: si riavvia.
Restart-Service Aurora

# 3. PostgreSQL e' vivo?
Get-Service postgresql*
Start-Service postgresql-x64-18
```

**Nove volte su dieci finisce a `Restart-Service Aurora`.** Riavviare non fa
danni: vedi la sezione 1.

---

### 4.2 «Non riesco a entrare» — una persona sola

**Come si riconosce.** Gli altri lavorano; una persona scrive la sua password
e viene rimandata al modulo di accesso, oppure legge «troppi tentativi
falliti».

**Che cosa e' successo.**

- ha sbagliato la password cinque volte in un quarto d'ora, e Aurora ha
  chiuso quel nome utente per un po'. E' voluto: e' la difesa contro chi prova
  a indovinare le password;
- oppure il suo profilo e' stato disattivato;
- oppure ha davvero dimenticato la password.

**Che cosa si fa.**

1. **Il blocco si scioglie da solo** in un quarto d'ora, purche' smetta di
   riprovare. Ogni tentativo in piu' fa ripartire il conteggio: va detto, o
   resta chiuso fuori all'infinito.
2. Se ha dimenticato la password: da Aurora, **Utenti** → la persona →
   «Assegna una password nuova». Aurora ne genera una di quattro parole
   italiane, che si detta al telefono. La persona sara' obbligata a cambiarla
   al primo accesso, e la password nuova azzera anche il blocco.
3. Se il profilo risulta disattivato: **Utenti** → la persona → «Riattiva».

**Se a non riuscire a entrare e' l'amministratore**, e non c'e' nessun altro
amministratore, si riassegna la password dal server:

```powershell
cd C:\Aurora
.\.venv\Scripts\activate
python scripts\reimposta_password.py NOME.UTENTE
```

Stampa la password nuova una volta sola.

> **Se invece non entra piu' nessuno, tutti insieme, subito dopo una
> modifica alla configurazione**, la causa e' quasi sempre una sola:
> `COOKIE_SECURE=true` senza https davanti. Il browser accetta la password e
> non rimanda mai il cookie. Si guarda `/diagnostica`, riga «Connessione
> cifrata»: lo dice.

---

### 4.3 «Il disco e' pieno»

**Come si riconosce.** La riga «Spazio sul disco» della diagnostica e' rossa,
oppure i caricamenti cominciano a fallire, oppure Windows avvisa.

**Che cosa e' successo.** L'archivio dei documenti cresce e non si cancella
mai: e' voluto (i dati sono il patrimonio dell'azienda), ed e' anche il motivo
per cui il disco prima o poi finisce.

**Che cosa si fa, in ordine.**

1. **Guardare che cosa occupa lo spazio.** La riga «Integrita' dell'archivio»
   dice quanti file ci sono; la riga «Spazio sul disco» dice quanto occupano e
   fra quanti mesi finiscono. Il resto lo occupano di solito i **salvataggi
   del database** in `E:\AuroraCopie`.

2. **Ridurre le copie tenute**, se sono loro. Nel file `C:\Aurora\.env`:

   ```
   BACKUP_KEEP=7
   ```

   Sette copie del database sono una settimana. Portandole a 3 si dimezza lo
   spazio. **La cartella `archivio/` dentro le copie non ruota e non si
   tocca**: e' l'unica copia dei documenti che esiste fuori dal server.

3. **Non cancellare niente da `D:\Aurora\storage`.** Quei file hanno per nome
   l'impronta del proprio contenuto e sono riferiti dal database: togliendone
   uno, un documento smette di scaricarsi e la diagnostica diventa rossa. **Se
   serve spazio si aggiunge un disco**, non si fa posto.

4. **L'unica cosa che si puo' togliere in sicurezza** e' il contenuto di
   `D:\Aurora\storage\tmp`, che sono caricamenti interrotti a meta'. Anche
   quello lo dice la diagnostica, riga «Integrita' dell'archivio».

---

### 4.4 «La posta non arriva piu'»

**Come si riconosce.** I messaggi nuovi non compaiono in Aurora. La riga
«Collegamento alla casella di posta» della diagnostica e' rossa o gialla.

**Che cosa e' successo.**

1. **Il segreto applicativo e' scaduto.** E' la causa piu' probabile e la piu'
   antipatica: Microsoft non avvisa nessuno, e da un giorno all'altro non
   arriva piu' niente. Aurora avvisa in anticipo - riga «Scadenza del segreto
   applicativo» - da trenta giorni prima, con evidenza crescente.
2. Qualcuno ha cambiato la password o i permessi della registrazione
   applicativa.
3. La rete verso Microsoft non c'e'.

**Che cosa si fa.**

Aprire **Posta → Configurazione posta** dentro Aurora. In cima alla pagina c'e'
la diagnostica della sola posta: da dove arriva, se i parametri ci sono tutti,
com'e' andato l'ultimo controllo, quando scade il segreto.

- il pulsante **«Controlla adesso»** prova subito e dice che cosa risponde
  Microsoft, in italiano;
- accanto a **ogni campo** c'e' un pulsante «Verifica» che prova quel valore
  da solo: cosi' si sa **quale** parametro e' sbagliato, invece di sapere solo
  che non funziona;
- se il segreto e' scaduto, si chiede all'ufficio informatico un segreto
  nuovo (la richiesta gia' scritta e' in `docs/RICHIESTA_IT.md`), lo si
  incolla nel campo, si scrive la data di scadenza nuova e si salva. **Non
  serve toccare nessun file sul server**: la pagina scrive il `.env` da sola.

**I messaggi non si perdono.** Quelli arrivati mentre Aurora non riusciva a
leggere restano nella casella e vengono presi al primo controllo riuscito.

---

### 4.5 «Aurora e' lentissima»

**Come si riconosce.** Le pagine ci mettono secondi. Succede a tutti.

**Che cosa e' successo, in ordine di probabilita'.**

1. **L'antivirus sta scansionando le cartelle di Aurora.** E' la causa piu'
   frequente in assoluto dopo un aggiornamento dell'antivirus, che a volte
   rimette le esclusioni com'erano. Le tre cartelle che devono essere escluse
   sono elencate in `docs/INSTALLAZIONE.md`, sezione 3, richiesta 1.
2. Il disco e' quasi pieno: vedi 4.3.
3. Qualcuno sta caricando un file enorme, o e' in corso la copia di sicurezza.
4. Il server sta facendo altro (aggiornamenti di Windows, un'altra
   applicazione).

**Che cosa si fa.**

```powershell
# Chi sta consumando il processore
Get-Process | Sort-Object CPU -Descending | Select-Object -First 5

# Quanto ci mette Aurora a rispondere, misurato
Measure-Command { Invoke-RestMethod http://localhost:8000/salute }
```

`/salute` risponde in meno di un decimo di secondo su un sistema che sta bene.
Se ci mette secondi, il problema e' sul server; se `/salute` e' veloce e le
pagine sono lente, il problema e' fra il server e il computer di chi guarda -
cioe' la rete.

**La riga «Collegamento al database» della diagnostica dice in quanti
millisecondi risponde PostgreSQL.** Sopra il mezzo secondo diventa gialla, ed
e' un buon indizio che il problema stia li'.

---

## 5. Come si ripristina una copia di sicurezza

E' l'operazione piu' delicata di tutte, e ha una procedura sua, scritta passo
per passo: **`docs/BACKUP_E_RIPRISTINO.md`, sezione 6.** Qui c'e' quello che
serve sapere prima di aprirla.

### Prima di cominciare, tre cose

1. **Non c'e' fretta.** Un ripristino fatto di corsa sul server sbagliato e'
   molto peggio del guasto che si sta riparando. Se il guasto e' «un documento
   e' sparito», Aurora nel frattempo continua a funzionare per tutti gli
   altri.
2. **Guardare che cosa c'e' da ripristinare**, prima di ripristinare:

   ```powershell
   cd C:\Aurora
   .\.venv\Scripts\activate
   python scripts\ripristino.py --elenco
   ```

   Mostra le copie disponibili con la data e che cosa contengono.
3. **Fermare Aurora**, altrimenti si sta scrivendo in un database che qualcuno
   sta usando:

   ```powershell
   Stop-Service Aurora
   ```

### Il ripristino

```powershell
python scripts\ripristino.py
```

Lo script chiede **due conferme**, e la prima non e' «si»: e' **scrivere per
esteso il nome del database** che si sta per sovrascrivere. E' voluto: chi lo
scrive lo ha letto, e chi lo ha letto non sta ripristinando sul server
sbagliato.

Poi rimette il database, rimette i file che mancano nell'archivio, e
**verifica la coerenza**: per ogni impronta che il database nomina, controlla
che il file ci sia davvero. E' il passo che distingue un ripristino da una
speranza di ripristino.

### Dopo

```powershell
Start-Service Aurora
```

E si guarda `/diagnostica`: la riga «Integrita' dell'archivio» deve essere
verde. Poi si scarica un documento, uno qualunque, e si controlla che si apra.

### La cosa piu' importante di questa sezione

**Il ripristino va provato prima che serva**, su una macchina diversa dal
server. La procedura e' in `docs/BACKUP_E_RIPRISTINO.md`, sezione 7, e va
rifatta **una volta all'anno**. Una copia di sicurezza che non e' mai stata
ripristinata non e' una copia di sicurezza: e' una speranza, e il giorno in cui
si scopre che non funzionava e' il giorno peggiore possibile per scoprirlo.

Data dell'ultima prova di ripristino riuscita: `_______________`

---

## 6. Le cose da fare ogni tanto

| Quando | Che cosa | Quanto dura |
|---|---|---|
| **ogni giorno** | aprire `/diagnostica` e guardare che sia verde | mezzo minuto |
| **ogni settimana** | controllare la riga «Copia di sicurezza»: deve dire «ieri notte» | mezzo minuto |
| **ogni mese** | guardare la riga «Spazio sul disco»: quanti mesi mancano | mezzo minuto |
| **ogni mese** | svuotare la quarantena della posta, se qualcuno non lo sta gia' facendo | dipende |
| **ogni tre mesi** | `python scripts\verifica_audit.py` | un minuto |
| **ogni anno** | **provare un ripristino** su un'altra macchina | mezza giornata |
| **quando la diagnostica lo dice** | tutto il resto | — |

**Se si deve fare una cosa sola, e' la prima.** La pagina di diagnostica e'
scritta apposta perche' trenta secondi al giorno bastino: quello che va
guardato sta in cima, e quello che va fatto e' scritto sotto.

---

## 7. Le cose da non fare mai

- **Non cancellare niente da `D:\Aurora\storage`.** Sono i documenti
  dell'azienda. I file hanno nomi che sembrano casuali - sono le impronte del
  loro contenuto - e ognuno e' riferito dal database.
- **Non cancellare righe dal database**, per nessuna ragione. Aurora non
  cancella mai niente: quello che non serve piu' si **disattiva**, e resta
  consultabile.
- **Non modificare la tabella `audit_logs`.** Il database non lo permette e
  c'e' una ragione: e' il registro che rende Aurora difendibile in sede di
  verifica aziendale.
- **Non copiare il file `.env` da un'altra macchina.** Contiene la
  configurazione di **questa**: password, percorsi, certificato. Sovrascriverlo
  fa puntare la produzione al database sbagliato.
- **Non installare una versione nuova senza aver fatto la copia prima.** La
  procedura e' `docs/AGGIORNAMENTO.md`, e il passo 2 e' proprio quello.
- **Non aprire Aurora verso internet.** Gira in rete locale ed e' fatta per
  quello. Se serve l'accesso da fuori, si passa dalla VPN aziendale.
- **Non usare l'ambiente di prova credendo che sia quello vero.** Si
  riconosce dalla barra laterale, che dice **«Aurora (PROVA)»**, e dalla porta,
  che e' la 8001.

---

## 8. I file che vale la pena conoscere

| File | A che serve | Quando si apre |
|---|---|---|
| `C:\Aurora\.env` | tutta la configurazione: percorsi, password, certificato | quando si cambia qualcosa sul server |
| `C:\Aurora\logs\aurora.log` | il registro | quando qualcosa non va |
| `docs\MANUALE_OPERATIVO.md` | questo documento | adesso |
| `docs\BACKUP_E_RIPRISTINO.md` | copie e ripristino, passo per passo | quando serve rimettere qualcosa |
| `docs\AGGIORNAMENTO.md` | come si installa una versione nuova | quando ne arriva una |
| `docs\INSTALLAZIONE.md` | come si installa da zero | su una macchina nuova |
| `docs\DA_FARE.md` | che cosa manca ancora ad Aurora | quando qualcuno chiede «si puo' fare che...» |
| `scripts\*.py` | le procedure: copia, ripristino, verifica del registro | quando la diagnostica lo dice |

**Tutti i file `.md` si aprono con il Blocco note** e si leggono cosi' come
sono. Sono scritti apposta per essere leggibili senza Aurora accesa - il che
conta il giorno in cui Aurora non si accende.

---

## 9. Chi chiamare

Da compilare al momento della consegna, e da tenere aggiornato.

| Per che cosa | Chi | Come |
|---|---|---|
| Aurora non funziona e questo manuale non basta | | |
| Il server, Windows, la rete, il firewall | ufficio informatico | |
| PostgreSQL, i backup dell'infrastruttura | ufficio informatico | |
| La casella di posta, Microsoft 365 | ufficio informatico | |
| Come si usa Aurora (non come si tiene accesa) | il referente dell'ufficio tecnico | |
| Decisioni sui dati (che cosa si conserva, chi vede che cosa) | il responsabile dell'ufficio tecnico | |

### Che cosa dire quando si chiama

Quattro cose, e fanno risparmiare mezz'ora a chi risponde:

1. **che cosa si e' visto**, con le parole di chi l'ha visto («la pagina dei
   documenti dice errore 500»);
2. **il codice di riferimento**, se c'era: e' quello fra parentesi quadre
   nella pagina di errore, tipo `3f9a2c11`;
3. **che cosa dice `/diagnostica`**: basta l'elenco delle righe non verdi;
4. **le ultime venti righe del registro**:

   ```powershell
   Get-Content C:\Aurora\logs\aurora.log -Tail 20
   ```

Con queste quattro cose chi risponde sa gia' quasi sempre di che si tratta.
Senza, la prima mezz'ora se ne va a chiedere.
