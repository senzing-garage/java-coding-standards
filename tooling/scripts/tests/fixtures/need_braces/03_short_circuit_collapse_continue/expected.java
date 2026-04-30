public class Foo
{
    public void method()
    {
        for (int i = 0; i < 10; i++) {
            if (skip(i)) continue;
            doIt(i);
        }
    }
}
