class LoneOperatorArgument
{
    // A lone operator-expression argument that fails to fit only because
    // its last row cannot also hold the `)` starts right after the `(`,
    // with its operator rows under it, when that takes no more rows than
    // moving the whole argument to a row of its own.
    void startsAfterTheParen()
    {
        if (a) {
            if (b) {
                if (c) {
                    fail("Unexpectedly succeeded in adding record: " + testData);
                    logDebug("ENTITY FOR RECORD " + recordKey + ": " + entityId);
                }
            }
        }
    }

    // Moving the argument to its own row wins when starting it after the
    // `(` would take more rows.
    void deepParenTakesMoreRows()
    {
        if (a) {
            statusReporter.reportProgressMessage("progress" + recordsProcessedNow + "done");
        }
    }

    // An operand that breaks internally leaves rows that do not start with
    // an operator under the argument, so the argument moves to its own row.
    void operandThatBreaksStaysOnItsOwnRow()
    {
        if (a) {
            assertTrue(exception.getMessage().contains("must") || exception.getMessage().contains("implement") || exception.getMessage().contains(SchedulingService.class.getName()));
        }
    }
}
