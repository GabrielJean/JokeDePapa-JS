# Jean le Bot Québécois

Un bot Discord qui raconte des blagues, roast tes amis, fait des compliments et lit tout ça en vocal avec un accent québécois (voix TTS GPT-4o) — et gère une file d’attente pour ne rien rater même si plusieurs commandes vocales sont lancées à la suite !

![Jean le Bot](https://emoji.gg/assets/emoji/8170-laugh-emoji.png)

## Fonctionnalités principales

- **Blagues reddit / québécoises / sons spéciaux**
- **Commandes slash fun** : `/joke`, `/jokeqc`, `/penis`, `/gpt`, `/roast`, `/compliment`, `/say-vc`, `/say-tc`, `/leave`, etc.
- **Lecture vocale intelligente** : le bot lit les blagues et messages dans le salon vocal (TTS GPT-4o, accent québécois configurable)
- **Compliments et “roasts” personnalisables**, avec option pour détailler des faits/mèmes pour personnaliser encore plus la vanne
- **File d’attente audio** : plusieurs lectures peuvent être programmées et seront jouées à la suite, pas de conflit même si plusieurs membres envoient des commandes en même temps
- **/help** intégré (liste toutes les commandes du bot)

## Configuration requise

- Python 3.9 ou plus
- **discord.py** ≥ 2.3
- Les modules Python suivants : `discord`, `discord.ext`, `requests`
- Un fichier de configuration `config.json` au format :
    ```json
    {
      "token": "TON_TOKEN_BOT_DISCORD_ICI",
      "tts_url": "URL_API_TTS",
      "azure_gpt_url": "URL_API_GPT",
      "api_key": "APIKEY_POUR_APIS"
    }
    ```
- Un dossier `./Audio` avec des fichiers MP3 (pour blagues québécoises et sons spéciaux)

## Installation

1. **Installe les modules**
    ```
    pip install discord.py requests
    ```

2. **Créer le fichier `config.json`** (voir plus haut)

3. **Ajoute tes sons MP3** dans le dossier `./Audio` (par exemple, `sort-pas-ton-penis.mp3`)

4. **Lance le bot**
    ```
    python tonbot.py
    ```

## Commandes principales

- `/help` – Affiche toutes les commandes du bot
- `/joke` – Joue une blague reddit en vocal
- `/jokeqc` – Joue une blague québécoise locale (mp3)
- `/leave` – Force le bot à quitter le vocal
- `/say-vc <texte>` – Fait lire du texte (accent configurable)
- `/say-tc <texte>` – Fait écrire du texte dans le salon
- `/gpt <question>` – Pose une question à GPT-4o et lit la réponse (vocal/text)
- `/roast @membre [intensité] [détails]` – Roast public fun, accent québécois (niveau 1 doux à 5 salé)
- `/compliment @membre [détails]` – Compliment personnalisé et vocal, accent québécois
- `/reset-prompts` – Réinitialise prompts système et configs TTS du server

## Fonctionnement de la file d’attente

Quand plusieurs membres lancent des commandes audio (lecture mp3/TTS), chaque demande est mise en file et jouée **dans l’ordre**.
👉 Personne ne sera “coupé” : tout sera lu dans l'ordre sans conflit.

## Bonus

- **Logs** : toute l’activité du bot est enregistrée dans `bot.log`
- **Multi-serveur** compatible
- **Accent configurable** (avec `/say-vc` ou `/gpt`)

## Exemples

```bash
/joke
/jokeqc
/roast @Martin 5 "Toujours en retard aux games, adore les pizzas"
/compliment @Julie "super à Mario Kart, meilleure rieuse du serveur"