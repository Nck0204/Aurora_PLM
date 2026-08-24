/* ==========================================================================
   Pulsante "Copia": mette negli appunti il testo di un altro elemento.

   Serve alla pagina che mostra la password assegnata a un utente. Il pulsante
   dichiara quale elemento copiare con l'attributo data-bersaglio:

       <code id="password-assegnata">chiave-fienile-rondine-tavolo</code>
       <button id="copia-password" data-bersaglio="password-assegnata">Copia</button>
       <span id="esito-copia"></span>

   JavaScript scritto a mano, servito dal nostro server: niente librerie,
   niente CDN, niente compilazione (regole 1 e 2 di CLAUDE.md).

   Ci sono due modi di copiare negli appunti e servono tutti e due.

   navigator.clipboard e' quello moderno, ma i browser lo mettono a
   disposizione solo in "contesto sicuro": https, oppure localhost. Aurora in
   azienda gira in rete locale, e finche' non ha un certificato viene aperta
   come http://nome-del-server, che contesto sicuro non e': li' quel modo non
   esiste proprio.

   document.execCommand('copy') e' quello vecchio, dichiarato superato, e
   funziona anche su http. Si tiene come ripiego finche' l'altro non e'
   disponibile ovunque.

   Se falliscono tutti e due non succede niente di grave: la password e'
   scritta li' sopra e si seleziona con il mouse. Il messaggio lo dice.
   ========================================================================== */

(function () {
    "use strict";

    var pulsante = document.getElementById("copia-password");
    if (!pulsante) {
        return;
    }

    var esito = document.getElementById("esito-copia");

    function mostraEsito(testo) {
        if (esito) {
            esito.textContent = testo;
        }
    }

    /* Il ripiego per http: si crea una casella di testo fuori dallo schermo,
       ci si mette dentro il testo, la si seleziona e si chiede al browser di
       copiare la selezione. Poi la si toglie. */
    function copiaAllaVecchiaManiera(testo) {
        var casella = document.createElement("textarea");
        casella.value = testo;
        casella.setAttribute("readonly", "");
        casella.style.position = "absolute";
        casella.style.left = "-9999px";
        document.body.appendChild(casella);
        casella.select();

        var riuscito = false;
        try {
            riuscito = document.execCommand("copy");
        } catch (errore) {
            riuscito = false;
        }

        document.body.removeChild(casella);
        return riuscito;
    }

    pulsante.addEventListener("click", function () {
        var bersaglio = document.getElementById(
            pulsante.getAttribute("data-bersaglio")
        );
        if (!bersaglio) {
            return;
        }

        var testo = bersaglio.textContent.trim();

        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(testo).then(
                function () {
                    mostraEsito("Copiata.");
                },
                function () {
                    mostraEsito(
                        copiaAllaVecchiaManiera(testo)
                            ? "Copiata."
                            : "Non sono riuscito a copiarla: selezionala a mano."
                    );
                }
            );
            return;
        }

        mostraEsito(
            copiaAllaVecchiaManiera(testo)
                ? "Copiata."
                : "Non sono riuscito a copiarla: selezionala a mano."
        );
    });
})();
