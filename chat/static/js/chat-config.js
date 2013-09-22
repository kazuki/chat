if (!window.Config) Config = new Object();

// Config.Title = 'チャット';
// Config.DefaultName = '名無し';
// Config.DefaultColor = 'black';
// Config.DefaultIcon = 'img/no-icon.png';
// Config.DefaultImageHashUrl = 'hash/';
// Config.DefaultIconSize = 1.2;
// Config.DefaultMsgCount = 50;

/* URLのプレフィックスを任意文字列で置換え短縮 */
Config.LinkMap = [
    ['ja.wikipedia.org/wiki/', 'Wikipedia']
];

/* メッセージを以下の正規表現で置き換えして表示 */
Config.Replaces = [
//  [/^(.*)$/, '$1']
];

/* 通知種別を定義 */
Config.NotificationTypes = [
//    ['hoge'],
//    ['sys', function(uid) { return uid == 'admin'; }]
];
