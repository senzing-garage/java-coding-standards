public class Demo
{
    void check(boolean cond, int bytes, int available)
    {
        assertTrue(
            available < bytes,
            "More bytes available than should be (" + bytes
            + "): " + available);
    }
}
