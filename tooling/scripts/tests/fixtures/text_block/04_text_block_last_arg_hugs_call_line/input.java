public class Demo
{
    public void run(SzEngine engine)
    {
        engine.addRecord(SzRecordKey.of(PASSENGERS, "ABC123"), """
            {
                "NAME_FULL": "Joe Schmoe"
            }
            """);
    }
}
