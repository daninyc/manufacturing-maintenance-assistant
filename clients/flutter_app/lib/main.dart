import 'package:flutter/material.dart';
import 'api_client.dart';

void main() => runApp(const MaintenanceApp());

class MaintenanceApp extends StatelessWidget {
  const MaintenanceApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '设备运维知识助手', debugShowCheckedModeBanner: false,
    theme: ThemeData(useMaterial3: true), home: const Workspace(),
  );
}

class Workspace extends StatefulWidget {
  const Workspace({super.key});
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> with WidgetsBindingObserver {
  final _server = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _question = TextEditingController();
  final _equipment = TextEditingController();
  final _document = TextEditingController();
  final _department = TextEditingController();
  final _policyVersion = TextEditingController(text: '0');
  int _classification = 1, _adminOffset = 0;
  bool _externalAllowed = false;
  String _visibility = 'department', _contentVersion = 'pending';
  ApiClient? _api;
  Map<String, dynamic>? _person;
  dynamic _result;
  String? _error;
  bool _busy = false, _suspended = false, _disposing = false;
  int _page = 0, _revision = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  void _clear() {
    if (!mounted || _disposing) return;
    setState(() {
      _revision++;
      _person = null;
      _result = null;
      _error = null;
      _busy = false;
      _question.clear();
      _equipment.clear();
      _password.clear();
      _document.clear();
      _department.clear();
      _policyVersion.text = '0';
      _classification = 1;
      _adminOffset = 0;
      _externalAllowed = false;
      _visibility = 'department';
      _contentVersion = 'pending';
      _page = 0;
    });
  }

  Future<void> _run(Future<dynamic> Function() work, {bool identity = false}) async {
    final revision = ++_revision;
    setState(() { _busy = true; _error = null; _result = null; });
    try {
      final value = await work();
      if (!mounted || revision != _revision || _suspended) return;
      setState(() {
        if (identity) {
          _person = value as Map<String, dynamic>;
          if (_person?['role'] != 'admin' && _page == 3) _page = 0;
        }
        else { _result = value; }
      });
    } catch (error) {
      if (mounted && revision == _revision) {
        setState(() => _error = error is ApiFailure
          ? '请求未完成：${error.code}。请检查连接或重新登录。'
          : '响应无法处理，请重试。');
      }
    } finally {
      if (mounted && revision == _revision) setState(() => _busy = false);
    }
  }

  Future<void> _login() async {
    final username = _username.text;
    final password = _password.text;
    _api?.close();
    try {
      _api = ApiClient(_server.text, onSessionCleared: _clear);
    } on ApiFailure {
      setState(() => _error = '请输入 HTTPS 服务器根地址，不要包含用户名、路径或参数。');
      return;
    }
    // Start login first: its synchronous clear must precede the UI revision.
    final pending = _api!.login(username, password);
    await _run(() => pending, identity: true);
    _password.clear();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      if (mounted) setState(() {
        _suspended = true; _result = null; _revision++; _busy = false;
        _document.clear(); _department.clear(); _policyVersion.text = '0';
        _classification = 1; _visibility = 'department';
        _externalAllowed = false; _contentVersion = 'pending';
      });
    } else {
      setState(() => _suspended = false);
      if (_api?.authenticated == true) _run(() => _api!.request('GET', ['me']), identity: true);
    }
  }

  @override
  void dispose() {
    _disposing = true;
    WidgetsBinding.instance.removeObserver(this);
    _api?.close();
    for (final controller in [_server, _username, _password, _question, _equipment,
                             _document, _department, _policyVersion]) {
      controller.dispose();
    }
    super.dispose();
  }

  Widget _field(TextEditingController controller, String label, {bool secret = false, int lines = 1}) =>
    Padding(padding: const EdgeInsets.only(bottom: 16), child: TextField(
      controller: controller, obscureText: secret, minLines: lines, maxLines: lines,
      enabled: !_busy, autocorrect: !secret, enableSuggestions: !secret,
      onChanged: (_) => setState(() {}),
      decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
    ));

  Widget _results(dynamic value) {
    if (value == null) return const SizedBox.shrink();
    if (value is List) {
      if (value.isEmpty) return const Text('当前没有可用记录。');
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch,
        children: value.map<Widget>((item) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 8), child: _results(item))).toList());
    }
    if (value is Map) {
      if (_page == 3 && _person?['role'] == 'admin' && value.containsKey('resource_id')) {
        return Card(child: ListTile(
          title: Text('${value['resource_id']} · ${value['status']}'),
          subtitle: Text('部门 ${value['department_id']} · 密级 ${value['classification']} · 版本 ${value['policy_version']}'),
          trailing: TextButton(onPressed: _busy ? null : () => setState(() {
            _document.text = '${value['resource_id']}';
            _department.text = '${value['department_id']}';
            _policyVersion.text = '${value['policy_version']}';
            _classification = value['classification'] as int;
            _visibility = value['visibility'] as String;
            _contentVersion = value['content_version'] as String;
            _externalAllowed = value['external_processing_allowed'] == true;
          }), child: const Text('选择')),
        ));
      }
      if (value.containsKey('items')) return _results(value['items']);
      if (value.containsKey('answer')) return Column(crossAxisAlignment: CrossAxisAlignment.start,
        children: [SelectableText('${value['answer']}'), _results(value['citations'])]);
      if (value.containsKey('evidence')) return Column(crossAxisAlignment: CrossAxisAlignment.start,
        children: [Text('状态：${value['status']}'), Text('${value['risk_notice']}'),
          const Divider(), _results(value['evidence']),
          const Text('建议（仅限有依据的模拟流程）'), _results(value['suggestions'])]);
      final excerpt = value['excerpt'] ?? value['summary'];
      if (excerpt != null) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SelectableText('$excerpt'),
        if (value['document_id'] != null && (value['chunk_id'] != null || value['source_type'] == 'knowledge'))
          TextButton(onPressed: _busy ? null : () => _run(() => _api!.request('GET', [
            'documents', '${value['document_id']}', 'chunks', '${value['chunk_id'] ?? value['source_ref']}',
          ])), child: const Text('重新校验并查看引用')),
      ]);
      return SelectableText(value.entries.map((entry) => '${entry.key}：${entry.value}').join('\n'));
    }
    return SelectableText('$value');
  }

  Future<void> _savePolicy(String status) => _run(() {
    final version = int.tryParse(_policyVersion.text);
    if (version == null || version < 0 || _document.text.trim().isEmpty ||
        _department.text.trim().isEmpty) throw const ApiFailure('INVALID_POLICY');
    return _api!.request('PATCH', ['admin', 'documents', _document.text.trim(), 'policy'], body: {
      'expected_version': version,
      'policy': {'resource_id': _document.text.trim(), 'department_id': _department.text.trim(),
        'visibility': _visibility, 'classification': _classification, 'status': status,
        'policy_version': version + 1, 'content_version': _contentVersion,
        'external_processing_allowed': _externalAllowed},
    });
  });

  Widget _administration() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    const Text('文档标签管理：管理权限不代表正文读取权限。保存草稿会暂停旧版本读取；409 冲突请刷新后重新选择。'),
    Wrap(spacing: 8, children: [
      OutlinedButton(onPressed: _busy ? null : () => _run(() => _api!.request('GET',
        ['admin', 'documents'], query: {'limit': '20', 'offset': '$_adminOffset'})),
        child: const Text('刷新策略列表')),
      TextButton(onPressed: _busy || _adminOffset == 0 ? null : () => setState(() {
        _adminOffset = (_adminOffset - 20).clamp(0, 100000).toInt(); _result = null;
      }), child: const Text('上一页')),
      TextButton(onPressed: _busy || _adminOffset >= 100000 ? null : () => setState(() {
        _adminOffset += 20; _result = null;
      }), child: const Text('下一页')),
      Text('偏移 $_adminOffset（切页后刷新）'),
    ]),
    _field(_document, '文档 ID（新建时填新 ID）'),
    _field(_department, '归属部门'), _field(_policyVersion, '当前策略版本（新建为 0）'),
    DropdownButton<int>(value: _classification, isExpanded: true,
      items: const [DropdownMenuItem(value: 0, child: Text('公开')),
        DropdownMenuItem(value: 1, child: Text('内部')),
        DropdownMenuItem(value: 2, child: Text('受限'))],
      onChanged: _busy ? null : (v) => setState(() => _classification = v!)),
    SwitchListTile(title: const Text('组织共享（否则仅所属部门）'),
      value: _visibility == 'organization', onChanged: _busy ? null : (v) => setState(() {
        _visibility = v ? 'organization' : 'department';
      })),
    SwitchListTile(title: const Text('允许发送模拟资料至 DeepSeek'), value: _externalAllowed,
      onChanged: _busy ? null : (v) => setState(() => _externalAllowed = v)),
    Wrap(spacing: 8, children: [
      FilledButton(onPressed: _busy ? null : () => _savePolicy('draft'), child: const Text('保存为草稿')),
      OutlinedButton(onPressed: _busy ? null : () => _savePolicy('disabled'), child: const Text('下线文档')),
    ]),
    const Text('保存后选择返回的新版本再操作。文件选择与上传页面仍在开发，不可直接将草稿标为已发布。'),
  ]);

  @override
  Widget build(BuildContext context) {
    final loggedIn = _person != null;
    return Scaffold(
      appBar: AppBar(title: const Text('设备运维知识助手'), actions: [
        if (loggedIn) TextButton(onPressed: () async {
          try { await _api?.logout(); } catch (_) {
            if (mounted) setState(() => _error = '本机已退出，服务器撤销未确认。');
          }
        }, child: const Text('退出')),
      ]),
      bottomNavigationBar: !loggedIn ? null : NavigationBar(selectedIndex: _page,
        onDestinationSelected: (page) => setState(() { _page = page; _result = null; _revision++; _busy = false; }),
        destinations: [const NavigationDestination(icon: Icon(Icons.search), label: '问答'),
          const NavigationDestination(icon: Icon(Icons.precision_manufacturing), label: '设备'),
          const NavigationDestination(icon: Icon(Icons.fact_check), label: '诊断'),
          if (_person?['role'] == 'admin')
            const NavigationDestination(icon: Icon(Icons.admin_panel_settings), label: '管理')]),
      body: SafeArea(child: _suspended ? const Center(child: Text('返回前台后重新校验会话')) :
        Align(alignment: Alignment.topCenter, child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 960),
          child: ListView(padding: const EdgeInsets.all(20), children: [
            const Text('模拟资料 · 不替代现场安全规程'), const SizedBox(height: 20),
            if (!loggedIn) ...[
              _field(_server, 'HTTPS 服务器地址'), _field(_username, '账号'),
              _field(_password, '密码', secret: true),
              FilledButton(onPressed: _busy ? null : _login, child: const Text('登录')),
            ] else ...[
              Text('部门：${_person!['department_id']}'), const SizedBox(height: 16),
              if (_page == 3 && _person?['role'] == 'admin') _administration(),
              if (_page == 1 || _page == 2) _field(_equipment, '设备编号'),
              if (_page == 0 || _page == 2) _field(_question, _page == 0 ? '问题' : '现象描述', lines: 3),
              if (_page == 1) Wrap(spacing: 8, runSpacing: 8, children: [
                for (final item in {'列表': <String>['equipment'], '详情': ['equipment', _equipment.text],
                  '报警': ['equipment', _equipment.text, 'alarms'], '维修': ['equipment', _equipment.text, 'maintenance']}.entries)
                  OutlinedButton(onPressed: _busy ? null : () => _run(() => _api!.request('GET', item.value)), child: Text(item.key)),
              ]) else if (_page < 3) FilledButton(onPressed: _busy ? null : () => _run(() => _api!.request('POST',
                [_page == 0 ? 'ask' : 'diagnose'], body: _page == 0
                  ? {'question': _question.text, 'mode': 'local'}
                  : {'equipment_id': _equipment.text, 'symptom': _question.text, 'mode': 'local'})),
                child: Text(_page == 0 ? '查询依据' : '汇总证据')),
            ],
            if (_busy) const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator()),
            if (_error != null) Padding(padding: const EdgeInsets.symmetric(vertical: 16), child: Text(_error!)),
            const SizedBox(height: 20), _results(_result),
          ])))),
    );
  }
}
