#!/usr/bin/env bash
set -euo pipefail
for row in '15237734448 approved2b a81dd53043b557edbccd1dcc4ab0db798a6c71db68aebbd12532272e600a2781' '15239450349 approved3a da593920add867904fc82f8f51207a6fe318fa42a2945e1880c5653112fe4ce1' '15251819732 approved4a bb74f4748e9e0b5bb13a32e838ed022ab66cf20a9bac2d75d0e7ebcf6c10a6d1' '15256940222 approved5a 5d2885cc4e19fdd0bb18a37a587145f9ab8699ef70efd385964ff11511f4edff'; do
  read -r id name sha <<< "$row"
  gh api "/repos/$GITHUB_REPOSITORY/actions/artifacts/$id/zip" > "/tmp/$name.zip"
  echo "$sha  /tmp/$name.zip" | sha256sum -c
done
curl --fail --location --retry 3 https://github.com/konoui/m-league-game-db/releases/download/20261120-2341-04338cbb/database.zip -o /tmp/mahjong-database.zip
echo 'e2e702402301ae136da71e3f79113f929e291779ff4997c24db5262aaa4ff548  /tmp/mahjong-database.zip' | sha256sum -c
python - <<'PY'
import shutil,zipfile
from pathlib import Path
with zipfile.ZipFile('/tmp/mahjong-database.zip') as z:
    c=[x for x in z.infolist() if not x.is_dir() and Path(x.filename).suffix.lower() in {'.sqlite3','.sqlite','.db','.db3'}]
    assert len(c)==1 and c[0].file_size==873754624
    with z.open(c[0]) as src,open('/tmp/mahjong-fixed.sqlite3','wb') as dst:shutil.copyfileobj(src,dst)
PY
echo 'edeccd86e100f6ffba88871d7c418a06488d3f515b22cdd2e2b9dced17573e6c  /tmp/mahjong-fixed.sqlite3' | sha256sum -c
chmod a-w /tmp/mahjong-fixed.sqlite3
