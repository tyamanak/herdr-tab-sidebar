# 内部の仕組み

[English](internals.md) | 日本語

このページは、herdr-tab-sidebar の [README](../README.ja.md) の続きです。

## 仕組み

`main.py` は短いプログラムで、Herdr がマニフェストの起動時フック・イベントフック・アクションから起動します。実行のたびに `session.snapshot` を読み、各ペインが持つべきトークンを計算して（`tab_sidebar/plan.py`）、差分だけを `pane.report_metadata` で書き込みます。常駐するものはありません。

| トークン | 付く先 | 意味 |
|---|---|---|
| `ts_m` | 一覧に出るタブの、すべてのエージェントのペイン | このプラグインが扱っている |
| `ts_rep` | タブの代表ペイン | このペインがタブの行になる |
| `ts_pos` | 代表ペイン | タブバーでの位置（ゼロ埋め） |
| `ts_group` | ワークスペースの最初の代表ペイン | 見出しの文字列 |
| `ts_label` | 代表ペイン | タブ名 |
| `ts_extra` | 代表ペイン | ほかのエージェントの数 `+N`。対応が必要なものがあれば `!` |

`agent.view.set`（source は `plugin:tyamanak.tab-sidebar`、label は `tabs`）は、代表ペインと、プラグインが印を付けていないペインを残し、`ts_m`、Herdr 自身の `workspace_order`、`ts_pos` の順で並べ替えます。ワークスペースの順序は Herdr のものなので、ワークスペースを並べ替えても、フックもトークンの変更も必要ありません。

実行は、プラグインの状態ディレクトリの下のロックで直列化しています。待っている間に、先の実行がそのイベントの分まで済ませていた場合、その実行は何もせずに終了します。ロックを持っている実行は、新しいスナップショットに変更が要らなくなるまで繰り返します（最長 8 秒。それを過ぎると、後続の実行が待っていない限り失敗します）。

## テスト

```sh
python3 -m unittest discover -s tests -t .
python3 tests/isolated/run.py
```

1 つ目のコマンドに必要なのは Python だけです。2 つ目には、PATH 上の `herdr`（または `--herdr PATH`）が必要です。一時ディレクトリの下に専用のヘッドレスの Herdr サーバー（設定・状態・プラグインのレジストリ・ソケット）を起動し、このチェックアウトをそこにリンクして、実際のフック・アクション・描画を動かします。そのサーバーの環境は一から組み立て、接続したサーバーが一時ディレクトリの中のソケットを報告しない限り先へ進まず、最後にそのディレクトリを削除します。自分のセッションと `~/.config/herdr` には触れません。

## デモ

```sh
python3 demo/run.py              # open the demo session in this terminal
python3 demo/run.py --text       # print the screen as text
python3 demo/run.py --svg FILE   # write the screen as an SVG image
```

デモは、テストと同じ種類の使い捨てのサーバーを使い、そこに架空のワークスペースとタブを入れます。エージェントは起動しません。ペインは用意したテキストを表示し、その状態は `herdr pane report-agent` で報告します。1 つ目の形式は、開く前に終了の方法（`ctrl+g`、続けて `q`）を伝え、終了したとき、または端末を閉じたときに、サーバーとそのディレクトリを削除します。Herdr の中から起動していて、自分のプレフィックスキーが `ctrl+g` の場合は、`--prefix` で別のキーを渡してください。
