public class Demo
{
    public void check(String value)
    {
        if (!(java.util.Objects.requireNonNull(
                 "a very long string literal that will not fit on one line at all")))
        {
            throw new IllegalStateException();
        }
    }
}
