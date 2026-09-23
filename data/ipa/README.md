# English UK IPA data

`en_UK.txt` is the tab-delimited English (Received Pronunciation) word list
from [open-dict-data/ipa-dict](https://github.com/open-dict-data/ipa-dict),
`data/en_UK.txt`. Upstream documents its English UK IPA data as derived from
ipacards and released under GPL-3.0. Keep that attribution and license with
redistributions of this dataset.

Refresh saved Quick Words transcriptions after updating the file with:

```sh
python manage.py sync_quickword_ipa --dry-run
python manage.py sync_quickword_ipa
```
