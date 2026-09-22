import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maintenance_assistant/main.dart';

void main() {
  for (final width in [320.0, 375.0, 414.0, 768.0]) {
    testWidgets('login fits width $width without an authenticated view', (tester) async {
      tester.view.physicalSize = Size(width, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const MaintenanceApp());
      expect(find.byType(TextField), findsNWidgets(3));
      expect(find.text('登录'), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.text('管理'), findsNothing);
      expect(find.text('保存为草稿'), findsNothing);
      expect(find.text('下线文档'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }
}
