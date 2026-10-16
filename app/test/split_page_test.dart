import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:receipt_tools/split_page.dart';

void main() {
  Widget page() => const MaterialApp(
        home: SplitPage(receipt: {
          'store_name': 'Test',
          'total': '10.00',
          'items': [
            {'name': 'A', 'price': '5.00', 'qty': '2'},
            {'name': 'B', 'price': '3.00', 'qty': '1'},
          ],
        }),
      );

  testWidgets('add and remove payer works', (tester) async {
    await tester.pumpWidget(page());
    expect(find.byIcon(Icons.person_remove), findsNWidgets(2));

    await tester.tap(find.byIcon(Icons.person_add));
    await tester.pump();
    expect(find.byIcon(Icons.person_remove), findsNWidgets(3));

    await tester.tap(find.byIcon(Icons.person_remove).last);
    await tester.pump();
    expect(find.byIcon(Icons.person_remove), findsNWidgets(2));
  });

  testWidgets('split dialog stepper changes the value', (tester) async {
    await tester.pumpWidget(page());
    // first split cell of the first row (qty 2 -> integer steps of 1);
    // widgetWithText(InkWell, ...) skips the plain '0' split-total text
    await tester.tap(find.widgetWithText(InkWell, '0').first);
    await tester.pumpAndSettle();
    expect(find.text('Split quantity (0 – 2)'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.add_circle_outline));
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    expect(find.text('1'), findsWidgets);
  });

  testWidgets('stepper increments on the FIRST click (qty 1 line)',
      (tester) async {
    await tester.pumpWidget(page());
    // row 2 has qty 1: its first split cell is the 3rd InkWell-wrapping '0'
    await tester.tap(find.widgetWithText(InkWell, '0').at(2));
    await tester.pump(); // dialog appears instantly (no entrance animation)
    expect(
        find.descendant(
            of: find.byType(AlertDialog), matching: find.text('0')),
        findsOneWidget);
    await tester.tap(find.byIcon(Icons.add_circle_outline));
    await tester.pump();
    expect(
        find.descendant(
            of: find.byType(AlertDialog), matching: find.text('1')),
        findsOneWidget);
  });

  testWidgets('line price/qty colored by split correctness', (tester) async {
    await tester.pumpWidget(page());
    // unsplit line: price text is red
    final red = tester.widgetList<Text>(find.text('5.00'))
        .where((t) => t.style?.color == Colors.red);
    expect(red, isNotEmpty);
  });
}
