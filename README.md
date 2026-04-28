适用于vrchat玩家的实时翻译方法
本方法需要下载livecaptions，如果你是pc玩家则无需额外使用此工具，如果是vr玩家，则此工具是读取livecaptions的数据库并且显示在vr模式下
利用livrcaptions（https://github.com/SakiRinn/LiveCaptions-Translator/tree/master），读取数据库，代码中使用的是绝对路径，请自行修改你的livecaptions数据库存放路径
        # 路径适配
        self.script_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        self.db_path = Path(r"D:\livecap\translation_history.db")//绝对路径，修改为自己的实际路径，或是与我的路径保持一致
        self.font_path = self.script_dir / "font" / "gnuunifontfull-pm9p.ttf"
        self.temp_texture = self.script_dir / "temp_texture.png"
