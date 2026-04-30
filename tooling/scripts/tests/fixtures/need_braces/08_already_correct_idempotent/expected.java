public class Foo
{
    public void method()
    {
        if (x == null) return;
        if (y != null) {
            y = null;
        }
        if (a > 0) {
            a = 0;
        } else {
            a = -1;
        }
    }
}
