# 内部の仕組み

[English](internals.md) | 日本語

このページは、herdr-tab-sidebar の [README](../README.ja.md) の続きです。

## 仕組み

`main.py` は、Herdr がマニフェストの起動時フック・イベントフック・アクションから呼び出す短いプログラムです。実行のたびに `session.snapshot` を読み、各ペインが持つべきトークンを計算して（`tab_sidebar/plan.py`）、差分だけを `pane.report_metadata` で書き込みます。常駐はしません。

| トークン | 付く先 | 意味 |
|---|---|---|
| `ts_m` | 一覧に表示されるタブの、全エージェントペイン | このプラグインの管理対象 |
| `ts_rep` | タブの代表ペイン | タブの行になるペイン |
| `ts_pos` | 代表ペイン | タブバーでの位置（ゼロ埋め） |
| `ts_group` | ワークスペース最初の代表ペイン | 見出しの文字列 |
| `ts_label` | 代表ペイン | タブ名 |
| `ts_extra` | 代表ペイン | 他のエージェントの数 `+N`。対応が必要なものがあれば `!` |

`agent.view.set`（source は `plugin:tyamanak.tab-sidebar`、label は `tabs`）は、代表ペインとプラグインが印を付けていないペインを残し、`ts_m`、Herdr 自身の `workspace_order`、`ts_pos` の順で並べ替えます。ワークスペースの並び順は Herdr 側が持つため、並べ替えてもフックの実行やトークンの変更は不要です。

実行は、プラグインの状態ディレクトリ下のロックで直列化されます。待機中に先行する実行がそのイベントの分まで済ませていた場合、その実行は何もせず終了します。ロックを持つ実行は、新しいスナップショットに変更が不要になるまで処理を繰り返します（最長 8 秒。これを超えると、後続の実行が待機していない限り失敗します）。

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

デモは、テストと同様の使い捨てサーバーを使い、架空のワークスペースとタブを用意します。エージェントは起動しません。ペインは用意したテキストを表示し、その状態を `herdr pane report-agent` で報告します。1 つ目の形式は、開く前に終了方法（`ctrl+g`、続けて `q`）を案内し、終了したときや端末を閉じたときに、サーバーとそのディレクトリを削除します。Herdr 内から起動していて、自身のプレフィックスキーが `ctrl+g` の場合は、`--prefix` で別のキーを指定してください。
