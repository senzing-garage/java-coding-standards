public class Demo
{
    @CsvSource({
        "sqlite3:///path%20with%20spaces/file.db, /path with spaces/file.db,",
        "sqlite3://na:na@/Users/test/Library/App%20Support/test.db, /Users/test/Library/App Support/test.db, na"
    })
    public void parse(String uriText, String expectedPath, String expectedUser)
    {
    }
}
