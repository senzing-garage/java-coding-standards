public class Demo
{
    void run(String expectedText, String result, String jsonValue)
    {
        assertEquals(expectedText.replaceAll("\\s", ""), result.replaceAll(
            "\\s",
            ""),
                     "Unexpected pretty-print result: " + jsonValue);
    }
}
