public class Foo
{
    public void method(Object x)
    {
        if (x == null) {
            throw new IllegalArgumentException(
                "Cannot specify a secondary value when "
                    + "the primary value is null. primary=[ " + x + " ]");
        }
    }
}
