# Richiesta all'ufficio informatico — accesso in lettura a una casella di posta

**A chi legge:** questo documento e' scritto per chi amministra Microsoft 365
in azienda e non ha mai sentito parlare del programma di cui si parla. Non
serve conoscerlo: quello che chiediamo sono cinque cose ben delimitate, e sotto
sono spiegate una per una con il perche' e con il comando gia' pronto.

**Data della richiesta:** ............................................

**Chi la manda:** ...................................................

---

## In due righe

Abbiamo un programma interno, **Aurora**, che tiene insieme i progetti e la
documentazione tecnica dei prodotti che sviluppiamo. Vogliamo che archivi da
solo la **corrispondenza con i clienti**, attaccandola al prodotto di cui
parla, cosi' che fra due anni chi riapre un progetto trovi le mail insieme ai
disegni invece che sparse nelle caselle personali di chi c'era.

Per farlo, Aurora deve poter **leggere** una casella di posta aziendale — una
sola, dedicata, che non esiste ancora o che decidete voi — e nient'altro.

---

## Che cosa chiediamo, in tutto

| # | Che cosa | Dove si fa | Quanto ci vuole |
|---|---|---|---|
| 1 | Una casella dedicata | Interfaccia di amministrazione di Microsoft 365 | 5 minuti |
| 2 | Una registrazione applicativa per Aurora | Portale Microsoft Entra (ex Azure AD) | 10 minuti |
| 3 | Il permesso di lettura di tipo applicazione, con consenso amministratore | Stesso portale | 5 minuti |
| 4 | Una regola che limiti Aurora a quella sola casella | PowerShell di Exchange Online | 10 minuti |
| 5 | Una regola di trasporto che copi sulla casella i messaggi con un codice prodotto nell'oggetto | Interfaccia di Exchange, oppure PowerShell | 15 minuti |

I punti da 1 a 4 servono perche' il programma funzioni. Il punto 5 e' quello
che fa arrivare i messaggi senza che nessuno debba ricordarsi di inoltrarli:
si puo' fare anche in un secondo momento.

---

## Che cosa **non** chiediamo

Vale la pena dirlo subito, perche' e' la prima domanda che viene in mente a chi
riceve una richiesta di questo tipo.

- **Nessun permesso di inviare, rispondere o cancellare.** Aurora legge, e
  l'unica cosa che scrive e' lo spostamento di un messaggio gia' archiviato in
  una sottocartella della stessa casella - e anche quello, solo se decidete di
  concederglielo (la scelta e' spiegata al punto 3).
- **Nessun accesso alle altre caselle.** Il punto 4 serve esattamente a
  garantirlo per iscritto, e non a parole: senza quella regola il permesso di
  Microsoft varrebbe su tutte le caselle dell'organizzazione, e non e' quello
  che vogliamo neanche noi.
- **Nessun accesso ai calendari, ai contatti, ai file o a Teams.**
- **Nessun utente e nessuna password.** Aurora si presenta come applicazione,
  con un segreto suo: non c'e' nessun account di persona da creare, e nessuna
  password di nessuno viene condivisa.
- **Niente di tutto questo esce dall'azienda.** Aurora gira su un server
  aziendale in rete locale; l'unico collegamento verso l'esterno e' quello
  verso Microsoft 365, per andare a prendere i messaggi.

---

## 1. Una casella dedicata

**Che cosa serve.** Una casella di posta aziendale su cui far arrivare la
corrispondenza da archiviare. Per esempio `ordini@azienda.it`, oppure
`archivio.tecnico@azienda.it`: il nome lo scegliete voi.

**Perche' una casella dedicata e non quella di una persona.** Tre ragioni:

1. la posta di una persona contiene anche cose sue, e Aurora non deve poterle
   leggere;
2. quando quella persona cambia ruolo o lascia l'azienda, l'archiviazione non
   si deve fermare;
3. una casella dedicata rende evidente a chiunque che cosa viene archiviato:
   basta aprirla e guardare.

**Deve essere una casella vera**, non un alias e non un gruppo di
distribuzione: Aurora legge la cartella "Posta in arrivo", e un alias non ne ha
una.

**Che cosa ci serve indietro:** l'indirizzo completo della casella.

---

## 2. Una registrazione applicativa

**Che cosa serve.** Una registrazione applicativa nel portale Microsoft Entra
(quello che si chiamava Azure Active Directory), che rappresenti Aurora.

**Come si fa.**

1. Portale Microsoft Entra → **Registrazioni app** → **Nuova registrazione**.
2. Nome: `Aurora - archiviazione posta` (o come preferite).
3. Tipi di account supportati: **solo questa organizzazione**.
4. URI di reindirizzamento: **nessuno**. Aurora non fa entrare nessuno da
   Microsoft: si presenta da sola, con il proprio segreto.
5. Dopo la creazione, nella scheda **Certificati e segreti** → **Nuovo segreto
   client**. Alla scadenza mettete quella che le vostre regole prevedono (12 o
   24 mesi).

**Attenzione al segreto.** Il valore si puo' leggere **solo nel momento in cui
viene creato**: dopo, il portale mostra solo l'identificativo del segreto, che
non serve a niente. Va copiato subito, ed e' il valore della colonna
**«Valore»**, non quello della colonna **«ID segreto»**.

**Che cosa ci serve indietro**, tre valori e una data:

| Dove si trova nel portale | Come si chiama |
|---|---|
| Panoramica della registrazione | **ID directory (tenant)** |
| Panoramica della registrazione | **ID applicazione (client)** |
| Certificati e segreti, colonna «Valore» | il **segreto** |
| Certificati e segreti, colonna «Scadenza» | la **data di scadenza** del segreto |

> **La data di scadenza ci serve davvero.** Quando il segreto scade, Aurora
> smette di leggere la posta e Microsoft non manda nessun avviso a nessuno:
> semplicemente, da un giorno all'altro non arriva piu' niente. Sapendo la data,
> il programma comincia a segnalarla trenta giorni prima, e ce ne accorgiamo
> mentre c'e' ancora tempo per chiedervene uno nuovo.

**Come ce li mandate.** Il segreto e' una password: mandatelo con lo stesso
mezzo con cui mandereste una password, non nel corpo di una mail insieme al
resto. Gli altri tre valori non sono riservati.

---

## 3. Il permesso di lettura, e il consenso

**Che cosa serve.** Un permesso solo:

> **`Mail.Read`**, di tipo **Applicazione** (non «Delegato»).

Piu' sotto c'e' una scelta da fare fra `Mail.Read` e `Mail.ReadWrite`: la
differenza fra i due riguarda una cosa sola, ed e' spiegata li'.

**Come si fa.** Nella registrazione appena creata: **API autorizzazioni** →
**Aggiungi autorizzazione** → **Microsoft Graph** → **Autorizzazioni
applicazione** → cercare `Mail.Read` → aggiungere. Poi, ed e' il passaggio che
si dimentica piu' spesso, **«Concedi consenso amministratore per
\<organizzazione\>»**: finche' non lo si preme, il permesso risulta aggiunto ma
non e' attivo, e Aurora riceve un rifiuto.

**Perche' «Applicazione» e non «Delegato».** Un permesso delegato vale mentre
c'e' una persona collegata che lo presta. Aurora legge la posta ogni cinque
minuti, anche di notte e ad agosto, senza nessuno davanti: se il permesso fosse
delegato, l'archiviazione si fermerebbe alla prima sessione scaduta.

### Una scelta che spetta a voi: `Mail.Read` oppure `Mail.ReadWrite`

Con `Mail.Read` Aurora legge i messaggi e nient'altro. **Non puo' pero'
spostarli**, e questo cambia qualcosa che e' bene sappiate prima e non dopo.

Aurora, dopo aver archiviato un messaggio, prova a **spostarlo** in una
sottocartella della stessa casella - `Elaborate`, oppure `Quarantena` se non ha
capito a quale prodotto appartiene - creando le due cartelle la prima volta che
servono. Serve a tenere pulita la posta in arrivo: dentro resta solo quello che
il programma non ha ancora elaborato, e chi apre la casella vede a colpo
d'occhio a che punto e'.

| | `Mail.Read` | `Mail.ReadWrite` |
|---|---|---|
| Aurora legge i messaggi | si' | si' |
| Aurora li sposta in `Elaborate` / `Quarantena` | **no** | si' |
| La posta in arrivo si svuota man mano | no: resta tutto li' | si' |
| Rischio di archiviare due volte lo stesso messaggio | nessuno | nessuno |
| Aurora puo' cancellare posta | **no** | **no**: il programma non lo fa mai |

**Se concedete `Mail.Read`** il programma funziona lo stesso e non perde e non
duplica niente: riconosce i messaggi gia' archiviati e li salta. Quello che
succede e' che la posta in arrivo continua a riempirsi, e prima o poi qualcuno
dovra' spostarla a mano. Nel registro di Aurora resta scritto, messaggio per
messaggio, che lo spostamento non e' stato possibile e quale permesso manca.

**Se concedete `Mail.ReadWrite`** date all'applicazione anche la possibilita'
tecnica di modificare e cancellare la posta di quella casella. Aurora non lo
fa - non c'e' nessuna funzione nel programma che cancelli una mail, ed e' una
regola scritta del progetto - ma il permesso ci sarebbe.

**Che cosa consigliamo.** `Mail.ReadWrite`, ristretto alla sola casella dal
punto 4 qui sotto: e' la combinazione che tiene ordinata la casella senza
allargare di un millimetro l'elenco delle caselle che Aurora puo' toccare. Ma
decidete voi: **con `Mail.Read` partiamo lo stesso**, e se poi la posta in
arrivo diventa scomoda si allarga il permesso in due minuti, senza rifare
niente del resto.

---

## 4. Limitare Aurora a quella sola casella

**Che cosa serve.** Una regola che dica: questa applicazione puo' leggere
**soltanto** la casella indicata, e nessun'altra dell'organizzazione.

**Perche'.** Il permesso `Mail.Read` di tipo applicazione, da solo, vale su
**tutte** le caselle del tenant. E' il motivo per cui una richiesta come questa
mette giustamente in allarme chi la riceve. La **Application Access Policy**
e' il modo con cui Microsoft permette di restringerlo, e la chiediamo noi:
serve a voi per poter dire di si' con tranquillita', e serve a noi perche' un
programma che puo' leggere tutta la posta dell'azienda e' un programma di cui
un domani qualcuno dovra' rispondere.

**I comandi, gia' pronti.** Da eseguire con il modulo `ExchangeOnlineManagement`
di PowerShell, sostituendo i tre valori fra parentesi angolari.

```powershell
# 1. Collegamento a Exchange Online
Connect-ExchangeOnline -UserPrincipalName <amministratore@azienda.it>

# 2. Un gruppo di sicurezza abilitato alla posta che contiene la sola casella
#    consentita. Serve perche' la regola si scrive su un gruppo, non su un
#    singolo indirizzo.
New-DistributionGroup -Name "Aurora - caselle consentite" `
                      -Alias "aurora-caselle" `
                      -PrimarySmtpAddress "aurora-caselle@azienda.it" `
                      -Type Security `
                      -Members "<ordini@azienda.it>"

# 3. La regola vera e propria: l'applicazione di Aurora puo' accedere
#    soltanto alle caselle che stanno in quel gruppo.
New-ApplicationAccessPolicy -AppId "<ID applicazione (client)>" `
                            -PolicyScopeGroupId "aurora-caselle@azienda.it" `
                            -AccessRight RestrictAccess `
                            -Description "Aurora puo' leggere solo la casella dell'archiviazione"

# 4. La verifica. Il primo comando deve rispondere "Granted",
#    il secondo "Denied".
Test-ApplicationAccessPolicy -Identity "<ordini@azienda.it>" -AppId "<ID applicazione (client)>"
Test-ApplicationAccessPolicy -Identity "<una.qualunque.altra@azienda.it>" -AppId "<ID applicazione (client)>"
```

> La regola puo' impiegare fino a un'ora a diventare efficace su tutto il
> tenant: se subito dopo averla creata la verifica risponde in modo diverso da
> quello atteso, conviene riprovare piu' tardi prima di cambiare qualcosa.

> **Se nel vostro tenant `New-ApplicationAccessPolicy` non e' piu' disponibile.**
> Microsoft sta sostituendo questo meccanismo con il **controllo degli accessi
> in base al ruolo per le applicazioni** (RBAC for Applications), che ottiene lo
> stesso risultato assegnando all'applicazione un ambito limitato a un gruppo di
> caselle. Per noi va bene ugualmente: quello che ci serve e' che Aurora possa
> leggere una casella sola. Scegliete voi il meccanismo, e diteci quale avete
> usato.

**Che cosa ci serve indietro:** la conferma che la regola e' attiva, con
l'esito dei due comandi di verifica.

---

## 5. Far arrivare i messaggi sulla casella

Questo punto e' diverso dagli altri quattro: non riguarda i permessi, riguarda
il fatto che nella casella ci arrivi qualcosa.

**Il problema.** La corrispondenza con i clienti arriva alle caselle personali
di chi segue i progetti. Chiedere a otto persone di ricordarsi di inoltrare
ogni messaggio a un indirizzo di archivio significa, in pratica, non archiviare
niente: funziona la prima settimana.

**Quello che chiediamo.** Una **regola di trasporto** che, quando l'oggetto di
un messaggio contiene un **codice prodotto**, ne mandi automaticamente una
copia nascosta alla casella dell'archiviazione. Il messaggio arriva ai
destinatari veri esattamente come prima: nessuno se ne accorge e nessuno deve
fare niente.

**Come e' fatto un codice prodotto.** Sono i codici dei nostri prodotti, del
tipo:

    RMS1100-24-110SW        CVT2200-48-24DC

cioe': alcune lettere, alcune cifre, un trattino, alcune cifre, un trattino,
alcune cifre e una sigla finale facoltativa. Nell'oggetto delle mail compaiono
spesso fra parentesi quadre, come `[RMS1100-24-110SW][V2][SPECS]`, ma non
sempre.

**L'espressione da usare nella regola:**

    [A-Za-z]{2,6}[0-9]{2,5}-[0-9]{1,4}-[0-9]{1,4}[A-Za-z0-9]{0,6}

**Dall'interfaccia di amministrazione:** Exchange admin center → **Flusso di
posta** → **Regole** → **Aggiungi una regola** → *Crea una nuova regola*:

- **Applica questa regola se:** «L'oggetto» → «corrisponde a questi modelli di
  testo» → incollare l'espressione qui sopra;
- **Esegui le operazioni seguenti:** «Aggiungi destinatari» → «alla casella Ccn»
  → la casella dell'archiviazione;
- **Modalita' della regola:** conviene attivarla prima **in modalita' di prova**
  per qualche giorno, per vedere quanto traffico intercetta prima di farla
  agire davvero.

**Lo stesso in PowerShell:**

```powershell
New-TransportRule -Name "Aurora - copia dei messaggi con codice prodotto" `
                  -SubjectMatchesPatterns "[A-Za-z]{2,6}[0-9]{2,5}-[0-9]{1,4}-[0-9]{1,4}[A-Za-z0-9]{0,6}" `
                  -BlindCopyTo "<ordini@azienda.it>" `
                  -Mode AuditAndNotify   # togliere per farla agire davvero
```

**Due avvertenze oneste.**

- L'espressione e' **larga**: intercettera' anche qualche messaggio che con i
  nostri prodotti non c'entra (un numero di fattura fatto allo stesso modo, per
  esempio). Non e' un guaio: Aurora mette da parte i messaggi che non sa a quale
  prodotto attribuire, e una persona li smista o li scarta. Preferiamo qualche
  messaggio in piu' che qualche messaggio perso.
- La regola vale per la posta **in arrivo e in uscita**, se non la restringete.
  A noi interessano tutte e due: una risposta che parte da qui e' parte della
  stessa conversazione.

Se una regola di trasporto non vi va bene — capita, e' una regola che agisce su
tutta la posta dell'azienda — l'alternativa e' che chi segue i progetti metta
la casella dell'archiviazione in copia quando scrive ai clienti. Funziona
meno bene, ma funziona.

---

## Riepilogo di quello che ci serve indietro

- [ ] Indirizzo della **casella** dedicata
- [ ] **ID directory (tenant)**
- [ ] **ID applicazione (client)**
- [ ] **Segreto** dell'applicazione (mandato come si manda una password)
- [ ] **Data di scadenza** del segreto
- [ ] Quale permesso avete concesso: **`Mail.Read`** oppure **`Mail.ReadWrite`**
- [ ] Conferma che il **consenso amministratore** e' stato concesso
- [ ] Conferma che la **restrizione a una sola casella** e' attiva
- [ ] Conferma che la **regola di trasporto** e' attiva (o che avete preferito
      di no)

Con questi valori la configurazione si completa dall'interfaccia del programma,
in cinque minuti e senza toccare nessun file: c'e' una pagina apposta, con un
pulsante che prova il collegamento e dice subito se qualcosa non torna.

---

## Se qualcosa non funziona

Il programma traduce da solo i rifiuti di Microsoft in frasi comprensibili, e
dice quale dei parametri e' sbagliato. Questi sono i tre casi che capitano
davvero:

| Che cosa dice il programma | Che cosa e' successo |
|---|---|
| «L'organizzazione indicata non esiste» | l'ID tenant e' sbagliato o incompleto |
| «Il segreto dell'applicazione non e' corretto» | e' stato copiato l'**ID segreto** invece del **Valore** |
| «All'applicazione manca il permesso di leggere la posta» | il consenso amministratore non e' stato concesso (punto 3) |
| «L'applicazione non e' autorizzata a leggere questa casella» | la regola del punto 4 non comprende quella casella, oppure non e' ancora efficace |

Per qualunque dubbio possiamo fare una prova insieme in dieci minuti: il
programma ha una pagina che verifica un parametro per volta e dice che cosa
risponde Microsoft.
