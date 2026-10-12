# herdr-tab-sidebar

[English](README.md) | 日本語

サイドバーの Agents パネルを縦型のタブ一覧に変える [Herdr](https://herdr.dev) プラグインです。エージェントがいるタブを 1 行ずつ表示し、ワークスペースごとの見出しの下にまとめます。

![エージェントのタブをワークスペースごとにまとめて表示した Agents パネル](docs/demo.svg)

この画像は、`demo/run.py --svg` で生成した架空のセッションです。[デモ](docs/internals.ja.md#デモ)を参照してください。

- ワークスペースは Spaces パネルの順（自分で並べた順）、タブはタブバーの順に並びます。
- 複数のエージェントがいるタブも 1 行で表示されます。`+1` は個別の行を持たないエージェントの数で、末尾の `!` はそのいずれかが blocked か done の状態であることを示します。
- 行を選択すると、そのタブの代表ペインにフォーカスが移ります。

## 動作要件

- Herdr 0.9.1 以降。
- Python 3.9 以降。Herdr サーバーの PATH 上で `python3` として見つかる必要があります。
- macOS または Linux。Linux では、まだ何も手で試していません。

## インストール

```sh
herdr plugin install tyamanak/herdr-tab-sidebar
herdr plugin action invoke tyamanak.tab-sidebar.apply
```

インストールしただけでは画面に変化はありません。`apply` が行レイアウトを `config.toml` に追加し、設定を再読み込みして行の内容を表示します。

`config.toml` を手作業で編集する必要はありません。`apply` がファイルの末尾に 8 行追記し、`release` がその 8 行を取り除いて元に戻します。変更のたびに、古いファイルのコピーを残します。

唯一の例外として、`config.toml` にすでに `[ui.sidebar.agents]` が定義されている場合、`apply` は拒否して何も変更しません。自分の定義を削除するかコメントアウトしてから `apply` を実行してください。[変更する内容](docs/config.ja.md#変更する内容)を参照してください。

## アンインストール

まず解除し、解除を確認できてからアンインストールしてください。アクションはバックグラウンドで動き、`invoke` はアクションが終わる前に戻ります。そのため、以下は 3 つの別々の手順であり、まとめて貼り付ける 1 つのブロックではありません。

1. 解除します。

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.release
   ```

2. 状態を問い合わせ、少し待ってからログで結果を確認します。

   ```sh
   herdr plugin action invoke tyamanak.tab-sidebar.status
   ```

   ```sh
   herdr plugin log list --plugin tyamanak.tab-sidebar
   ```

   最新の `status` のエントリーが `state: released` で終わっていれば、次へ進みます。そうならない場合は、[解除が終わらないとき](docs/config.ja.md#解除が終わらないとき)を参照してください。

3. アンインストールします。

   ```sh
   herdr plugin uninstall tyamanak.tab-sidebar
   ```

プラグインの行を `config.toml` から手作業で取り除く場合は、[手作業で取り除く](docs/config.ja.md#手作業で取り除く)を参照してください。

## 制限

- エージェントのいないタブには行がありません。Herdr が一覧に表示するのは、エージェントが動いているペインのみです。
- 複数のエージェントがいるタブのほかのエージェントには、プラグインの適用中、次/前のエージェントへの移動ではたどり着けません。
- 適用中は、プラグインが Herdr 自身による Agents パネルの並び順と、Herdr の Agent ビューを置き換えます。ビューを設定する別のプラグインとの併用は試していません。

すべての項目は[制限](docs/usage.ja.md#制限)に記載されています。

## ドキュメント

- [使い方](docs/usage.ja.md): 動作要件、確認、アクション、更新、制限。
- [設定](docs/config.ja.md): `apply` が書き込む内容と、元に戻す方法。
- [内部の仕組み](docs/internals.ja.md): 仕組み、テスト、デモ。

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
