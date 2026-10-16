import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:receipt_tools/main.dart';

void main() {
  testWidgets('requests screen renders with the server field', (tester) async {
    await tester.pumpWidget(const PriceHunterApp());
    await tester.pump(); // let the (failing) bootstrap settle into error state
    expect(find.byIcon(Icons.settings), findsOneWidget);
  });
}
