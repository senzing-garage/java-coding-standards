public class Demo
{
    public void run()
    {
        assertThrows(
            SampleException.class,
            () -> new ReportRecord(ReportCode.SOURCE_SUMMARY,
                                   null,
                                   100L,
                                   "SUMMARY"));
    }
}
